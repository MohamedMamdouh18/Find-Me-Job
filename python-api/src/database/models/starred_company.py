from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlmodel import Field

from .base_model import BaseModel
from ...shared import now


class StarredCompany(BaseModel, table=True):
    """A company the user tracks. The table name is historical: rows are no longer only
    starred ones, because "scrape this board" and "I want to work here" are two facts and
    Phase 3 reads the second as a scoring signal. See CONTEXT.md and ADR 0001.
    """

    __tablename__ = "starred_companies"  # type: ignore[assignment]

    id: Optional[int] = Field(default=None, primary_key=True)
    company_name: str = Field(unique=True, nullable=False, index=True)  # stored lowercase
    careers_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=now)

    # I want to work here. Every row that predates the split is one of these.
    starred: bool = Field(default=True, sa_column_kwargs={"server_default": sa.true()})
    # Scrape this company every run. Default false so an upgrade starts nothing.
    in_workflow: bool = Field(default=False, sa_column_kwargs={"server_default": sa.false()})

    # How this company gets fetched, decided by sniffing the careers URL rather than
    # configured. `unknown` is "not checked yet", which is not the same as unreadable —
    # the switch is unavailable for both, but only one of them is a dead end.
    fetch_method: str = Field(default="unknown", sa_column_kwargs={"server_default": "unknown"})
    # Why, when fetch_method is unreadable. Shown on the row, so the user is told rather
    # than left watching a company that will never return a job.
    fetch_note: Optional[str] = None
    ats: Optional[str] = None
    ats_token: Optional[str] = None

    last_scraped_at: Optional[datetime] = None
    last_job_count: Optional[int] = None
    # Two consecutive empty fetches turn the row off rather than retrying forever.
    consecutive_empty: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
