from datetime import datetime
from typing import Optional

from sqlmodel import Field

from .base_model import BaseModel
from ...shared import now


class SeenJob(BaseModel, table=True):
    __tablename__ = "seen_jobs"  # type: ignore

    id: str = Field(primary_key=True)
    seen_at: datetime = Field(default_factory=now, index=True)
    # Normalised company::title::location, so the same role syndicated by a second
    # source is recognised as one job. Nullable on purpose: rows that predate this
    # column have nothing left to compute it from — this table keeps an id and a
    # timestamp, not the job — and a null never matches, so they keep working on id
    # alone exactly as before.
    fingerprint: Optional[str] = Field(default=None, index=True)
