from datetime import datetime

from sqlmodel import Field

from .base_model import BaseModel
from ...shared import now


class AppSetting(BaseModel, table=True):
    """User-editable configuration, one row per key.

    Deliberately untyped at the database level: the endgame is every .env key
    editable from the dashboard, and a typed column per setting makes that a
    migration each time. Types and validation live in services/settings.py.
    """

    __tablename__ = "app_settings"  # type: ignore[assignment]

    key: str = Field(primary_key=True)
    value: str = Field(nullable=False)
    updated_at: datetime = Field(default_factory=now)
