import logging
import threading
from sqlmodel import Session

from . import settings
from .emailing import process_and_send_email_if_needed
from .intake import save_pending_job
from .keywords import extract_or_get_keywords
from .run_context import RunContext, redact_secrets
from .scoring import score_job
from ..database.core import engine
from ..database.models import FilteredJob
from ..database.models.enums import AiStatus, UserStatus
from ..database.repositories import (
    FilteredJobRepository,
    PendingJobRepository,
    WorkflowRunRepository,
)
from ..scrapers import SOURCES
from .. import shared
from ..shared import send_telegram

logger = logging.getLogger(__name__)
_run_lock = threading.Lock()


def run_pipeline(trigger: str = "schedule") -> None:
    """Orchestrates a complete job search, scrape, score, email, and notify cycle."""
    if not _run_lock.acquire(blocking=False):
        logger.warning("Pipeline run already in progress, skipping")
        return

    try:
        with Session(engine) as session:
            run_repo = WorkflowRunRepository(session)
            run = run_repo.start(trigger=trigger)
            session.commit()

            ctx = RunContext(run.id, session)
            ctx.emit("run.start", f"Run {run.id} started via {trigger}")

            try:
                # 1. Keywords from CV
                cv_text, keywords = extract_or_get_keywords(ctx)

                # 2. Scrape each configured source
                total_queued = 0
                for source_name, fetch_fn in SOURCES.items():
                    try:
                        jobs = fetch_fn(ctx, keywords)
                        queued_count = sum(
                            1 for j in jobs if save_pending_job(session, j) == "queued"
                        )
                        total_queued += queued_count
                        ctx.emit(
                            f"scrape.{source_name}.saved",
                            f"Saved {queued_count} new pending jobs from {source_name}",
                        )
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
                for idx, job in enumerate(pending_jobs, 1):
                    ctx.wait(scoring_delay)
                    ctx.emit(
                        "score.start",
                        f"Scoring job {idx}/{queue_depth}: {job.title} at {job.company}",
                        detail=f"Job {idx} of {queue_depth}",
                        done=idx,
                        total=queue_depth,
                    )

                    try:
                        score, cover_letter = score_job(ctx, job, cv_text)
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

                # 4. Finish run and derive stats.
                # jobs_scraped is what this run actually queued, not the queue depth:
                # the queue can still hold rows this run did not scrape.
                run_repo.finish(run.id, status="success", jobs_scraped=total_queued)
                session.commit()
                ctx.emit(
                    "run.finish",
                    f"Run {run.id} finished successfully. Scored: {run.jobs_scored}, Matched: {run.jobs_matched}",
                )

                failures_line = (
                    f" | Failed: {scoring_failures}" if scoring_failures else ""
                )
                summary_text = (
                    f"Find Me a Job run finished\n"
                    f"Scraped: {run.jobs_scraped} | Scored: {run.jobs_scored} | "
                    f"Fit: {run.jobs_matched}{failures_line}\n"
                    # read through the module: shared.DASHBOARD_URL is rebound after tunnel detection
                    f"Dashboard: {shared.DASHBOARD_URL}"
                )
                send_telegram(summary_text)

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
                run_repo.finish(run.id, status="failed", error=redact_secrets(str(e)))
                session.commit()

            finally:
                ctx.reset()

    finally:
        _run_lock.release()
