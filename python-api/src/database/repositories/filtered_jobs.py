from datetime import datetime

from sqlmodel import Session, select

from ..models import FilteredJob


class FilteredJobRepository:
    def __init__(self, session: Session):
        self.session = session

    def exists(self, job_id: str) -> bool:
        return self.session.get(FilteredJob, job_id) is not None

    def add(self, job: FilteredJob):
        self.session.merge(job)

    def get(self, job_id: str) -> FilteredJob | None:
        return self.session.get(FilteredJob, job_id)

    def get_all(self) -> list[FilteredJob]:
        statement = select(FilteredJob).order_by(FilteredJob.updated_at.desc())  # type: ignore
        return list(self.session.exec(statement).all())

    def update_status(self, job_id: str, user_status: str) -> bool:
        job = self.session.get(FilteredJob, job_id)
        if not job:
            return False
        job.user_status = user_status
        self.session.add(job)
        return True

    def delete_older_than(self, cutoff: datetime):
        statement = select(FilteredJob).where(FilteredJob.updated_at < cutoff)
        for job in self.session.exec(statement).all():
            self.session.delete(job)
