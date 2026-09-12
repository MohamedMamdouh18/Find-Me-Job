from datetime import datetime
from typing import Optional

from sqlmodel import Field

from .base_model import BaseModel
from .enums import RunStatus, RunTrigger
from ...shared import now


class WorkflowRun(BaseModel, table=True):
    __tablename__ = "workflow_runs"  # type: ignore[assignment]

    id: Optional[int] = Field(default=None, primary_key=True)
    # Domain is RunTrigger in models/enums.py: schedule | manual | resume
    trigger: str = Field(default=RunTrigger.SCHEDULE.value)
    # Domain is RunStatus in models/enums.py: running | success | failed | paused | stopped
    status: str = Field(default=RunStatus.RUNNING.value, index=True)
    started_at: datetime = Field(default_factory=now, index=True)
    finished_at: Optional[datetime] = None
    jobs_scraped: int = Field(default=0)  # pending jobs picked up this run
    jobs_scored: int = Field(default=0)  # rows written to filtered_jobs
    jobs_matched: int = Field(default=0)  # of those, ai_status == fit
    error: Optional[str] = None
    stage: Optional[str] = None
    stage_detail: Optional[str] = None
