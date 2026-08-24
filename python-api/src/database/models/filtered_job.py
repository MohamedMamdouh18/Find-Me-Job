from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlmodel import Column, Field

from .base_model import BaseModel
from .enums import AiStatus, UserStatus
from ...shared import now


class FilteredJob(BaseModel, table=True):
    __tablename__ = "filtered_jobs"  # type: ignore

    # Declared here so a fresh create_all() and the alembic chain produce the same
    # indexes. Names must match migration d7e4c2f81b60.
    __table_args__ = (
        sa.Index("ix_filtered_jobs_updated_at", "updated_at"),
        sa.Index("ix_filtered_jobs_created_at", "created_at"),
        sa.Index("ix_filtered_jobs_score", "score"),
        sa.Index("ix_filtered_jobs_company", "company"),
        sa.Index("ix_filtered_jobs_website", "website"),
        sa.Index("ix_filtered_jobs_location", "location"),
        sa.Index("ix_filtered_jobs_status_updated", "ai_status", "user_status", "updated_at"),
    )

    id: str = Field(primary_key=True)
    title: str
    company: str
    location: str
    applylink: str
    description: str
    website: str
    score: int = Field(default=0)
    application_document: Optional[str] = None
    easy_apply: bool = Field(default=False)
    ai_status: AiStatus = Field(sa_column=Column(sa.String(), nullable=False))
    user_status: UserStatus = Field(
        default=UserStatus.NEW,
        sa_column=Column(sa.String(), nullable=False, default=UserStatus.NEW.value),
    )
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
