from datetime import datetime

from sqlmodel import Session, select

from ..models import SeenJob


class SeenJobRepository:
    def __init__(self, session: Session):
        self.session = session

    def exists(self, job_id: str) -> bool:
        return self.session.get(SeenJob, job_id) is not None

    def add(self, job_id: str):
        self.session.merge(SeenJob(id=job_id))

    def delete_older_than(self, cutoff: datetime):
        statement = select(SeenJob).where(SeenJob.seen_at < cutoff)
        for job in self.session.exec(statement).all():
            self.session.delete(job)
