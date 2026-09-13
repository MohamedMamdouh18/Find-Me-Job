from typing import Optional

from pydantic import BaseModel


class ScheduleUpdate(BaseModel):
    """Every field optional: the dashboard sends only what changed."""

    enabled: Optional[bool] = None
    mode: Optional[str] = None
    every_n_hours: Optional[int] = None
    at_minute: Optional[int] = None
    at_time: Optional[str] = None
    retention_at_time: Optional[str] = None
