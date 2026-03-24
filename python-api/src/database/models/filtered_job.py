from datetime import datetime
from typing import Optional
from sqlmodel import Field
from .base_model import BaseModel
from ...shared import now


class FilteredJob(BaseModel, table=True):
    __tablename__ = "filtered_jobs"  # type: ignore

    id: str = Field(primary_key=True)
    title: str
    company: str
    location: str
    applylink: str
    description: str
    website: str
    score: int = Field(default=0)
    cover_letter: Optional[str] = None
    easy_apply: bool = Field(default=False)
    ai_status: str  # fit | not_fit
    user_status: str = Field(default="new")  # new | applied | wont_apply
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
