import logging
from sqlmodel import Session

from ..database.models import PendingJob
from ..database.repositories import (
    BlockedCompanyRepository,
    PendingJobRepository,
    SeenJobRepository,
)
from ..schemas.jobs import PendingJobRequest

logger = logging.getLogger(__name__)


def save_pending_job(session: Session, job: PendingJobRequest | PendingJob) -> str:
    """Saves a scraped job.

    Enforces the company blocklist before queueing: if the company is blocked,
    the job is recorded as seen so it is never fetched again, and "blocked" is returned
    without adding it to pending_jobs.

    Returns:
        "blocked" | "already_seen" | "queued"
    """
    seen_repo = SeenJobRepository(session)
    blocked_repo = BlockedCompanyRepository(session)
    pending_repo = PendingJobRepository(session)

    if blocked_repo.is_blocked(job.company):
        seen_repo.add(job.id)
        session.commit()
        return "blocked"

    if seen_repo.exists(job.id):
        return "already_seen"

    db_job = PendingJob(**job.model_dump()) if isinstance(job, PendingJobRequest) else job
    pending_repo.add(db_job)
    seen_repo.add(job.id)
    session.commit()
    return "queued"
