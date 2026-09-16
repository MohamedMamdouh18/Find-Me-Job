from datetime import datetime

from sqlalchemy import delete
from sqlmodel import Session, select

from ..models import SeenJob


class SeenJobRepository:
    def __init__(self, session: Session):
        self.session = session

    def exists(self, job_id: str) -> bool:
        return self.session.get(SeenJob, job_id) is not None

    def fingerprint_exists(self, fingerprint: str) -> bool:
        """A null fingerprint never matches: rows written before the column existed
        have nothing to compute one from, and they keep deduplicating on id alone."""
        if not fingerprint:
            return False
        return (
            self.session.exec(
                select(SeenJob).where(SeenJob.fingerprint == fingerprint)
            ).first()
            is not None
        )

    def known(self, job_ids: list[str], fingerprints: list[str]) -> tuple[set[str], set[str]]:
        """Which of these ids and fingerprints are already on record.

        Asked in bulk, before the intake cap is applied: a job that cannot be queued must
        not consume the run's budget, or a feed's unchanged top results fill the cap every
        night and a newly posted job below them never gets in.
        """
        ids = set()
        prints = set()
        for chunk in range(0, len(job_ids), 400):  # SQLite caps variables per statement
            batch = job_ids[chunk:chunk + 400]
            ids |= {
                row.id for row in self.session.exec(select(SeenJob).where(SeenJob.id.in_(batch)))
            }
        wanted = [fp for fp in fingerprints if fp]
        for chunk in range(0, len(wanted), 400):
            batch = wanted[chunk:chunk + 400]
            prints |= {
                row.fingerprint
                for row in self.session.exec(select(SeenJob).where(SeenJob.fingerprint.in_(batch)))
                if row.fingerprint
            }
        return ids, prints

    def add(self, job_id: str, fingerprint: str | None = None):
        self.session.merge(SeenJob(id=job_id, fingerprint=fingerprint))

    def delete_older_than(self, cutoff: datetime):
        self.session.execute(delete(SeenJob).where(SeenJob.seen_at < cutoff))
