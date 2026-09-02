from datetime import datetime
from typing import Optional

from sqlmodel import Field

from .base_model import BaseModel
from ...shared import now


class WorkflowRun(BaseModel, table=True):
    __tablename__ = "workflow_runs"  # type: ignore[assignment]

    id: Optional[int] = Field(default=None, primary_key=True)
    trigger: str = Field(default="schedule")  # "schedule" | "manual"
    status: str = Field(default="running", index=True)  # "running" | "success" | "failed"
    started_at: datetime = Field(default_factory=now, index=True)
    finished_at: Optional[datetime] = None
    jobs_scraped: int = Field(default=0)  # pending jobs picked up this run
    jobs_scored: int = Field(default=0)  # rows written to filtered_jobs
    jobs_matched: int = Field(default=0)  # of those, ai_status == fit
    error: Optional[str] = None
    stage: Optional[str] = None
    stage_detail: Optional[str] = None
