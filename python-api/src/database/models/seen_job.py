from datetime import datetime

from sqlmodel import Field

from .base_model import BaseModel
from ...shared import now


class SeenJob(BaseModel, table=True):
    __tablename__ = "seen_jobs"  # type: ignore
    id: str = Field(primary_key=True)
    seen_at: datetime = Field(default_factory=now)
