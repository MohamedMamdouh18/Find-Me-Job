from datetime import datetime
from typing import Optional
from sqlmodel import Field
from .base_model import BaseModel
from ...shared import now


class CVKeywords(BaseModel, table=True):
    __tablename__ = "cv_keywords"  # type: ignore

    id: Optional[int] = Field(default=None, primary_key=True)
    cv_hash: str
    keywords: str
    updated_at: datetime = Field(default_factory=now)
