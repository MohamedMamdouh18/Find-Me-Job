from datetime import datetime

from sqlmodel import Session, select

from ..models import PendingJob


class PendingJobRepository:
    def __init__(self, session: Session):
        self.session = session

    def exists(self, job_id: str) -> bool:
        return self.session.get(PendingJob, job_id) is not None

    def add(self, job: PendingJob):
        self.session.merge(job)

    def get_all(self) -> list[PendingJob]:
        statement = select(PendingJob).order_by(PendingJob.created_at.desc())  # type: ignore
        return list(self.session.exec(statement).all())

    def delete(self, job_id: str) -> bool:
        job = self.session.get(PendingJob, job_id)
        if not job:
            return False
        self.session.delete(job)
        return True

    def delete_older_than(self, cutoff: datetime):
        statement = select(PendingJob).where(PendingJob.created_at < cutoff)
        for job in self.session.exec(statement).all():
            self.session.delete(job)
