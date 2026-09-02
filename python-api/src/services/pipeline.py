import logging
import threading
from sqlmodel import Session

from . import settings
from .emailing import process_and_send_email_if_needed
from .intake import save_pending_job
from .keywords import extract_or_get_keywords
from .run_context import RunContext
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
                for source_name, fetch_fn in SOURCES.items():
                    try:
                        jobs = fetch_fn(ctx, keywords)
                        queued_count = sum(
                            1 for j in jobs if save_pending_job(session, j) == "queued"
                        )
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

                for idx, job in enumerate(pending_jobs, 1):
                    ctx.wait(scoring_delay)
                    ctx.emit(
                        "score.start",
                        f"Scoring job {idx}/{queue_depth}: {job.title} at {job.company}",
                        detail=f"Job {idx} of {queue_depth}",
                        done=idx,
                        total=queue_depth,
                    )

                    score, cover_letter = score_job(ctx, job, cv_text)
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
                    session.commit()

                    ctx.emit(
                        "score.done",
                        f"Scored job {idx}/{queue_depth}: {job.title} (score={score}, {ai_status.value})",
                        detail=f"Scored {idx}/{queue_depth}",
                        done=idx,
                        total=queue_depth,
                    )

                # 4. Finish run and derive stats
                run_repo.finish(run.id, status="success", jobs_scraped=queue_depth)
                session.commit()
                ctx.emit(
                    "run.finish",
                    f"Run {run.id} finished successfully. Scored: {run.jobs_scored}, Matched: {run.jobs_matched}",
                )

                summary_text = (
                    f"Find Me a Job run finished\n"
                    f"Scraped: {run.jobs_scraped} | Scored: {run.jobs_scored} | Fit: {run.jobs_matched}\n"
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
                run_repo.finish(run.id, status="failed", error=str(e))
                session.commit()

    finally:
        _run_lock.release()
