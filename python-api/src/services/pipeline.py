import logging
import threading
import time
from sqlmodel import Session

from . import settings
from .emailing import process_and_send_email_if_needed
from .intake import save_pending_job
from .keywords import extract_or_get_keywords
from .net_abort import abort_active_calls
from .run_context import (
    PauseRequested,
    RunContext,
    redact_secrets,
    set_current_progress,
)
from .scoring import score_job
from ..database.core import engine
from ..database.models import FilteredJob
from ..database.models.enums import AiStatus, LockHolder, RunStatus, RunTrigger, UserStatus
from ..database.repositories import (
    FilteredJobRepository,
    PendingJobRepository,
    SeenJobRepository,
    SourceRepository,
    WorkflowRunRepository,
)
from ..scrapers import COMPANIES, FILTERED_SOURCES, SOURCES
from ..scrapers.base import prefilter
from .identity import fingerprint as job_fingerprint
from .. import shared
from .notifications import notify

logger = logging.getLogger(__name__)
_run_lock = threading.Lock()

# Who holds _run_lock. Read without holding it, so it can be momentarily None
# while a holder is mid-handover: release_run_lock() clears it before releasing,
# and a run sets it only after acquiring. A failed acquire already proves the
# lock is held, so None there means in-transition, never held-by-a-run — which
# is why the checks below treat None as "worth waiting for" rather than "skip".
_lock_holder: LockHolder | None = None

# How long a run waits for retention to let go. Retention is a handful of DELETEs;
# longer than this means something is wrong, and waiting forever would stack runs
# up behind max_instances=1.
RETENTION_WAIT_SECONDS = 120

# The one skip that is normal and needs no record: max_instances=1 working.
SKIP_RUN_IN_PROGRESS = "a run is already in progress"

# Pause is cooperative: the route sets this event, the scoring loop notices it between
# jobs, and ctx.wait() returns early so the signal is not sat on for a whole delay.
# A plain Event is enough because the pipeline runs on an APScheduler thread in this
# same process — the same reason Progress can be a process global.
_pause_event = threading.Event()


# Stop is pause plus two things: it kills the in-flight LLM call instead of waiting
# for it, and it ends the run in a state resume refuses. Setting _pause_event too
# means every place that already watches for an interrupt needs no second check.
_stop_event = threading.Event()


def try_acquire_lock_for_retention() -> bool:
    """Non-blocking claim on the run lock, for jobs that must not overlap a run.

    Used by retention, which would otherwise delete rows mid-scrape whenever the
    user schedules the pipeline across retention's hour.
    """
    global _lock_holder
    if not _run_lock.acquire(blocking=False):
        return False
    _lock_holder = LockHolder.RETENTION
    return True


def release_run_lock() -> None:
    global _lock_holder
    _lock_holder = None
    _run_lock.release()


def _acquire_for_pipeline() -> tuple[bool, str]:
    """Claim the lock for a run. Returns (acquired, reason it was not).

    Another *run* holding it means skip — that is the documented rule and what
    max_instances=1 expects. *Retention* holding it is a different case: it is
    seconds of DELETEs, and skipping there would drop a whole scheduled run with
    no workflow_runs row, which neither coalesce nor misfire_grace_time can
    recover because the fire was consumed, not missed. Every interval that
    divides 24 includes midnight, where retention sits by default, so waiting is
    the common path rather than an edge case.
    """
    global _lock_holder
    if _run_lock.acquire(blocking=False):
        _lock_holder = LockHolder.PIPELINE
        return True, ""
    if _lock_holder not in (None, LockHolder.RETENTION):
        return False, SKIP_RUN_IN_PROGRESS

    deadline = time.monotonic() + RETENTION_WAIT_SECONDS
    while time.monotonic() < deadline:
        if _run_lock.acquire(timeout=0.5):
            _lock_holder = LockHolder.PIPELINE
            return True, ""
        # A run took the lock first: skip, as the rule says. None stays in the
        # loop — that is a handover in flight, not a run holding the lock.
        if _lock_holder not in (None, LockHolder.RETENTION):
            return False, SKIP_RUN_IN_PROGRESS
    return False, f"retention still running after {RETENTION_WAIT_SECONDS}s"


def request_pause() -> None:
    _pause_event.set()


def request_stop() -> None:
    _stop_event.set()
    _pause_event.set()
    abort_active_calls()


def is_pause_requested() -> bool:
    """Read by GET /api/runs/current so the dashboard can show an interrupt that has
    been asked for but not yet landed — otherwise the run looks like it ignored the
    click."""
    return _pause_event.is_set()


def is_stop_requested() -> bool:
    return _stop_event.is_set()


def _emit_interrupted(ctx: RunContext, run_id: int, done: int, total: int) -> None:
    stopped = _stop_event.is_set()
    word = "stopped" if stopped else "paused"
    ctx.emit(
        f"run.{word}",
        f"Run {run_id} {word} with {total - done} jobs still queued",
        detail=f"{word.capitalize()} after {done} of {total}",
        done=done,
        total=total,
    )


def _record_dropped_run(trigger: str, reason: str) -> None:
    """Write a failed row for a fire the scheduler already consumed.

    coalesce and misfire_grace_time cannot retry a consumed fire, so without a row
    a lost night shows up nowhere the dashboard can see. A second trigger during a
    run is not recorded — that one is the documented, harmless case.
    """
    try:
        with Session(engine) as session:
            repo = WorkflowRunRepository(session)
            run = repo.start(trigger=trigger)
            session.flush()
            repo.finish(run.id, RunStatus.FAILED.value, error=f"Run dropped: {reason}")
            session.commit()
    except Exception:
        logger.exception("Could not record the dropped run")


def _unseen(session, jobs: list) -> list:
    """The jobs from this batch that are not already on record.

    Runs before the cap, not after. A source hands back much the same list every night, so
    capping first spends the whole budget on jobs that will be recognised and dropped a
    moment later — and a posting that appeared today, sitting below the cut, never enters
    the queue at all, while the run still reports a healthy "kept 80".
    """
    if not jobs:
        return jobs
    prints = [job_fingerprint(job.company, job.title, job.location) for job in jobs]
    known_ids, known_prints = SeenJobRepository(session).known([job.id for job in jobs], prints)
    return [
        job
        for job, print_ in zip(jobs, prints)
        if job.id not in known_ids and print_ not in known_prints
    ]


def _gate(source_name: str, jobs: list, keywords: dict, remaining: int) -> tuple[list, dict]:
    """What a source is allowed to queue this run, best first.

    Two limits and one filter. A feed carries the whole world, so it is filtered against
    the CV keywords; a company row is not, because the user named that employer and a
    sideways role their keywords miss is exactly the job they want. Both then meet the
    per-source ceiling and whatever is left of the run budget — which is what stops one
    feed with six figures of jobs behind it from being the only source a run reaches.

    Returns the jobs to save and how many were dropped, so the run can report both: a
    filter set too tight and a dead source look identical without those two numbers.
    """
    kept = prefilter(jobs, keywords) if source_name in FILTERED_SOURCES else list(jobs)
    ceiling = min(settings.get_intake_max_per_source(), max(remaining, 0))
    allowed = kept[:ceiling]
    # Two different facts, reported separately: jobs the filter judged irrelevant, and
    # jobs there was no room for tonight. One number cannot tell a filter set too tight
    # from a budget set too low, which is the whole reason these counts exist.
    return allowed, {"filtered": len(jobs) - len(kept), "capped": len(kept) - len(allowed)}


def _walk_order(sources: dict) -> list:
    """Companies first, then feeds.

    Duplicates are resolved first-wins, so the order is what decides which copy of a role
    survives: the board's original, with the full description and the real application
    form, rather than a feed's syndication of it.
    """
    return sorted(sources.items(), key=lambda pair: pair[0] != COMPANIES)


def _enabled_sources(session, ctx) -> dict:
    """The registry minus what the user switched off.

    Asks which sources are disabled rather than which are enabled, so a source with
    no row runs: that keeps an upgrade silent and a newly registered module working
    before anyone has opened Settings. Every source being off is a valid state — the
    queue is still drained below, the same way a resume drains it.
    """
    disabled = SourceRepository(session).disabled_names()
    if disabled:
        ctx.emit(
            "scrape.disabled",
            f"Skipping disabled sources: {', '.join(sorted(disabled))}",
        )
    return {name: fetch for name, fetch in SOURCES.items() if name not in disabled}


def run_pipeline(trigger: str = RunTrigger.SCHEDULE.value) -> None:
    """Orchestrates a complete job search, scrape, score, email, and notify cycle."""
    acquired, reason = _acquire_for_pipeline()
    if not acquired:
        logger.warning("Pipeline run skipped: %s", reason)
        if reason != SKIP_RUN_IN_PROGRESS:
            _record_dropped_run(trigger, reason)
        return

    try:
        with Session(engine) as session:
            run_repo = WorkflowRunRepository(session)

            # A deliberate pause outranks the schedule: the cron does not silently
            # override it. Manual triggers and resume do, since those are the user
            # asking for work now. get_latest() is used rather than get_recent()
            # because the latter expires stale rows as a side effect.
            if trigger == RunTrigger.SCHEDULE:
                latest = run_repo.get_latest()
                if latest and latest.status == RunStatus.PAUSED:
                    logger.info(
                        "Workflow is paused (run %s); skipping the scheduled run", latest.id
                    )
                    return

            run = run_repo.start(trigger=trigger)
            session.commit()

            # A pause requested before this run started is not this run's business.
            _pause_event.clear()
            _stop_event.clear()
            ctx = RunContext(run.id, session, interrupt=_pause_event)
            ctx.emit("run.start", f"Run {run.id} started via {trigger}")

            paused = False
            try:
                # 1. Keywords from CV. Interruptible: the CV call hits the LLM when
                # the hash changed, and that is a phase a stop must not sit through.
                try:
                    cv_text, keywords = extract_or_get_keywords(ctx)
                except PauseRequested:
                    paused = True
                    cv_text, keywords = "", {}
                    _emit_interrupted(ctx, run.id, 0, 0)

                # 2. Scrape each configured source.
                # A resume picks up where a paused run stopped, so it skips scraping
                # entirely: the leftover queue IS the remaining work. Keywords are
                # still read above because scoring needs cv_text, and that call only
                # hits the LLM when the CV hash changed.
                total_queued = 0
                sources: dict = {}
                if trigger == RunTrigger.RESUME:
                    ctx.emit("scrape.skipped", "Resuming a paused run; not re-scraping")
                elif not paused:
                    # Inside the branch, not above it: a resume that is not scraping
                    # has nothing to say about which sources are switched off.
                    sources = _enabled_sources(session, ctx)
                # No keywords means prefilter scores everything zero and every feed job is
                # dropped as irrelevant. That is indistinguishable from six dead feeds unless
                # the run says so out loud.
                if not paused and not (keywords.get("titles") or keywords.get("skills")):
                    ctx.emit(
                        "keywords.empty",
                        "No titles or skills came out of the CV, so every job from a feed "
                        "will be dropped as irrelevant. Companies and LinkedIn are unaffected.",
                        level="warning",
                    )

                budget = settings.get_intake_max_per_run()
                for source_name, fetch_fn in _walk_order(sources):
                    # Between sources, so a stop does not sit through every scraper.
                    if _pause_event.is_set():
                        paused = True
                        break
                    try:
                        jobs = fetch_fn(ctx, keywords)
                        offered = len(jobs)
                        # Order is load-bearing: the cap truncates, so whatever sits at the
                        # front is what gets queued. Sources hand back newest-first, and
                        # prefilter's sort is stable, so recency survives the relevance
                        # ranking among jobs that score the same.
                        jobs = _unseen(session, jobs)
                        allowed, dropped = _gate(
                            source_name, jobs, keywords, budget - total_queued
                        )
                        dropped["already_seen"] = offered - len(jobs)
                        ctx.emit(
                            f"scrape.{source_name}.gate",
                            f"{source_name}: offered {offered}, kept {len(allowed)}, "
                            f"dropped {dropped['already_seen']} already seen, "
                            f"{dropped['filtered']} as irrelevant and "
                            f"{dropped['capped']} over the cap",
                            context={"offered": offered, "kept": len(allowed), **dropped},
                        )
                        queued_count = sum(
                            1 for j in allowed if save_pending_job(session, j) == "queued"
                        )
                        total_queued += queued_count
                        ctx.emit(
                            f"scrape.{source_name}.saved",
                            f"Saved {queued_count} new pending jobs from {source_name}",
                        )
                    except PauseRequested:
                        # Not a source failure; must not be swallowed as one.
                        paused = True
                        break
                    except Exception as e:
                        logger.exception(f"Scraper {source_name} failed: {e}")
                        ctx.emit(
                            f"scrape.{source_name}.failed",
                            f"Source {source_name} failed: {e}",
                            level="error",
                            context=str(e),
                        )

                # 3. Process pending queue
                pending_repo = PendingJobRepository(session)
                pending_jobs = pending_repo.get_all()
                queue_depth = len(pending_jobs)
                ctx.emit("queue.depth", f"{queue_depth} jobs pending scoring", total=queue_depth)

                filtered_repo = FilteredJobRepository(session)
                scoring_delay = settings.get_scoring_delay()
                filtering_score = settings.get_filtering_score()
                auto_email = settings.get_auto_email()

                scoring_failures = 0
                for idx, job in enumerate(pending_jobs if not paused else [], 1):
                    ctx.wait(scoring_delay)

                    # The row just scored is already committed and drained, so the
                    # untouched remainder of the queue is what a resume has left.
                    if _pause_event.is_set():
                        paused = True
                        _emit_interrupted(ctx, run.id, idx - 1, queue_depth)
                        break

                    ctx.emit(
                        "score.start",
                        f"Scoring job {idx}/{queue_depth}: {job.title} at {job.company}",
                        detail=f"Job {idx} of {queue_depth}",
                        done=idx,
                        total=queue_depth,
                    )

                    try:
                        score, cover_letter = score_job(ctx, job, cv_text)
                    except PauseRequested:
                        # Not a failure. Nothing was written or drained for this job,
                        # so it stays queued and a resume re-scores it from the top.
                        paused = True
                        _emit_interrupted(ctx, run.id, idx - 1, queue_depth)
                        break
                    except Exception as e:
                        # Isolate per job, like the scraper loop above. The row is dropped
                        # rather than left queued: it is already recorded in seen_jobs, so
                        # a job that always fails would otherwise re-fail at this same
                        # index every run and strand every job behind it.
                        scoring_failures += 1
                        logger.exception(f"Scoring failed for job {job.id}: {e}")
                        ctx.emit(
                            "score.failed",
                            f"Scoring failed for {job.title} at {job.company}: {e}",
                            level="error",
                            context=str(e),
                            detail=f"Job {idx} of {queue_depth}",
                            done=idx,
                            total=queue_depth,
                        )
                        pending_repo.delete(job.id)
                        session.commit()
                        continue

                    is_fit = score >= filtering_score
                    ai_status = AiStatus.FIT if is_fit else AiStatus.NOT_FIT
                    user_status = UserStatus.NEW

                    if is_fit and auto_email:
                        if process_and_send_email_if_needed(ctx, job, cover_letter):
                            user_status = UserStatus.EMAIL_SENT

                    filtered_job = FilteredJob(
                        id=job.id,
                        title=job.title,
                        company=job.company,
                        location=job.location,
                        applylink=job.applylink,
                        description=job.description,
                        website=job.website,
                        score=score,
                        application_document=cover_letter,
                        easy_apply=job.easy_apply,
                        user_status=user_status,
                        ai_status=ai_status,
                    )
                    filtered_repo.add(filtered_job)
                    # Drain the queue. Without this every run re-scores the whole
                    # backlog: save_pending_job dedups on seen_jobs so nothing is
                    # re-queued, but nothing was ever removed either.
                    pending_repo.delete(job.id)
                    session.commit()

                    ctx.emit(
                        "score.done",
                        f"Scored job {idx}/{queue_depth}: {job.title} (score={score}, {ai_status.value})",
                        detail=f"Scored {idx}/{queue_depth}",
                        done=idx,
                        total=queue_depth,
                    )

                # A pause is only observed between jobs, so a request arriving in a
                # phase the loop never reaches — during scraping with nothing left to
                # queue, or while the final job was being scored — would otherwise be
                # dropped, and the 01:00 cron would start as if nothing happened.
                paused = paused or _pause_event.is_set()

                # 4. Finish run and derive stats.
                # jobs_scraped is what this run actually queued, not the queue depth:
                # the queue can still hold rows this run did not scrape.
                # Pausing closes the row too: finished_at bounds the window finish()
                # counts over, so the stats describe the segment that actually ran.
                if paused:
                    final_status = (
                        RunStatus.STOPPED if _stop_event.is_set() else RunStatus.PAUSED
                    )
                else:
                    final_status = RunStatus.SUCCESS
                run_repo.finish(run.id, status=final_status.value, jobs_scraped=total_queued)
                session.commit()

                failures_line = (
                    f" | Failed: {scoring_failures}" if scoring_failures else ""
                )

                if paused:
                    left = pending_repo.count()
                    # A stopped run is not resumable, so it must not be described as
                    # paused nor pointed at a Resume that answers 409.
                    stopped = final_status is RunStatus.STOPPED
                    word = "stopped" if stopped else "paused"
                    next_step = (
                        "Start a fresh run from the dashboard"
                        if stopped
                        else "Resume from the dashboard"
                    )
                    ctx.emit(
                        "run.finish",
                        f"Run {run.id} {word}. Scored: {run.jobs_scored}, {left} still queued",
                    )
                    summary_text = (
                        f"Find Me a Job run {word}\n"
                        f"Scored: {run.jobs_scored} | Fit: {run.jobs_matched}"
                        f"{failures_line} | Still queued: {left}\n"
                        f"{next_step}: {shared.DASHBOARD_URL}"
                    )
                else:
                    ctx.emit(
                        "run.finish",
                        f"Run {run.id} finished successfully. Scored: {run.jobs_scored}, Matched: {run.jobs_matched}",
                    )
                    summary_text = (
                        f"Find Me a Job run finished\n"
                        f"Scraped: {run.jobs_scraped} | Scored: {run.jobs_scored} | "
                        f"Fit: {run.jobs_matched}{failures_line}\n"
                        # read through the module: shared.DASHBOARD_URL is rebound after tunnel detection
                        f"Dashboard: {shared.DASHBOARD_URL}"
                    )

                notify(summary_text)

            except Exception as e:
                logger.exception(f"Pipeline run {run.id} failed: {e}")
                ctx.emit(
                    "run.failed",
                    f"Run failed: {e}",
                    level="error",
                    context=str(e),
                )
                # workflow_runs.error is rendered in the dashboard, so it is the same
                # class of sink as a log line and gets the same redaction.
                run_repo.finish(
                    run.id, status=RunStatus.FAILED.value, error=redact_secrets(str(e))
                )
                session.commit()

            finally:
                ctx.reset()
                # Progress is a process global. Leaving the finished run in it makes
                # GET /api/runs/current report a live run forever, which hides the
                # dashboard's run controls until the container restarts.
                set_current_progress(None)
                _pause_event.clear()
                _stop_event.clear()

    finally:
        release_run_lock()
