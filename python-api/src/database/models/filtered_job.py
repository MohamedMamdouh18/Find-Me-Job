from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlmodel import Column, Field

from .base_model import BaseModel
from .enums import AiStatus, UserStatus
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
    ai_status: AiStatus = Field(sa_column=Column(sa.String(), nullable=False))
    user_status: UserStatus = Field(
        default=UserStatus.NEW,
        sa_column=Column(sa.String(), nullable=False, default=UserStatus.NEW.value),
    )
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
