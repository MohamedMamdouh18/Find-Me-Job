from datetime import datetime
from typing import Optional

from sqlmodel import Field

from .base_model import BaseModel
from ...shared import now


class RunEvent(BaseModel, table=True):
    __tablename__ = "run_events"  # type: ignore[assignment]

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="workflow_runs.id", index=True)
    ts: datetime = Field(default_factory=now, index=True)
    level: str = Field(default="info")  # "info" | "warning" | "error"
    stage: str  # e.g. "scrape.linkedin", "score", "email"
    message: str
    context: Optional[str] = None  # JSON blob, nullable
