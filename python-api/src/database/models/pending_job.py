from datetime import datetime

from sqlmodel import Field

from .base_model import BaseModel
from ...shared import now


class PendingJob(BaseModel, table=True):
    __tablename__ = "pending_jobs"  # type: ignore
    id: str = Field(primary_key=True)
    title: str
    company: str
    location: str
    applylink: str
    description: str
    website: str
    created_at: datetime = Field(default_factory=now)
