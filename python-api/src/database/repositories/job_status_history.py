from sqlmodel import Session, select

from ..models import JobStatusHistory
from ..models.enums import UserStatus


class JobStatusHistoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, job_id: str, status: UserStatus) -> JobStatusHistory:
        entry = JobStatusHistory(job_id=job_id, status=status.value)
        self.session.add(entry)
        return entry

    def get_for_job(self, job_id: str) -> list[JobStatusHistory]:
        statement = (
            select(JobStatusHistory)
            .where(JobStatusHistory.job_id == job_id)
            .order_by(JobStatusHistory.changed_at.asc())  # type: ignore[arg-type]
        )
        return list(self.session.exec(statement).all())
