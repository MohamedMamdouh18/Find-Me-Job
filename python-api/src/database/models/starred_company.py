from datetime import datetime
from typing import Optional

from sqlmodel import Field

from .base_model import BaseModel
from ...shared import now


class StarredCompany(BaseModel, table=True):
    __tablename__ = "starred_companies"  # type: ignore[assignment]

    id: Optional[int] = Field(default=None, primary_key=True)
    company_name: str = Field(unique=True, nullable=False, index=True)  # stored lowercase
    careers_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=now)
