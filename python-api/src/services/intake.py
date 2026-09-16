import logging
from sqlmodel import Session

from ..database.models import PendingJob
from ..database.repositories import (
    BlockedCompanyRepository,
    PendingJobRepository,
    SeenJobRepository,
)
from ..schemas.jobs import PendingJobRequest
from .identity import fingerprint as job_fingerprint

logger = logging.getLogger(__name__)


def save_pending_job(session: Session, job: PendingJobRequest | PendingJob) -> str:
    """Saves a scraped job.

    Enforces the company blocklist before queueing: if the company is blocked,
    the job is recorded as seen so it is never fetched again, and "blocked" is returned
    without adding it to pending_jobs.

    Two identities are checked, not one. The id is exact but only unique within a source,
    so the same role reached through a company board and through a feed would otherwise
    be two queue entries, two LLM calls and two cards. The fingerprint catches that. It
    is first-wins by design: walk order decides which copy survives, and the pipeline
    walks companies before feeds so the copy that lands is the original rather than the
    syndication.

    Returns:
        "blocked" | "already_seen" | "queued"
    """
    seen_repo = SeenJobRepository(session)
    blocked_repo = BlockedCompanyRepository(session)
    pending_repo = PendingJobRepository(session)

    print_ = job_fingerprint(job.company, job.title, job.location)

    if blocked_repo.is_blocked(job.company):
        seen_repo.add(job.id, print_)
        session.commit()
        return "blocked"

    if seen_repo.exists(job.id) or seen_repo.fingerprint_exists(print_):
        return "already_seen"

    db_job = PendingJob(**job.model_dump()) if isinstance(job, PendingJobRequest) else job
    pending_repo.add(db_job)
    seen_repo.add(job.id, print_)
    session.commit()
    return "queued"
