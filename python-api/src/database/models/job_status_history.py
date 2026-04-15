from datetime import datetime
from typing import Optional

from sqlmodel import Field

from .base_model import BaseModel
from ...shared import now


class JobStatusHistory(BaseModel, table=True):
    __tablename__ = "job_status_history"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(foreign_key="filtered_jobs.id", index=True)
    status: str = Field(nullable=False)
    changed_at: datetime = Field(default_factory=now)
