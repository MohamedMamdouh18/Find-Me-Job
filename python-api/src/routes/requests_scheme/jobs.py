from typing import Optional

from pydantic import BaseModel

from ...database.models.enums import AiStatus, UserStatus


class PendingJobRequest(BaseModel):
    id: str
    title: str
    company: str
    location: str
    applylink: str
    description: str
    website: str
    easy_apply: bool = False


class FilteredJobRequest(BaseModel):
    id: str
    title: str
    company: str
    location: str
    applylink: str
    description: str
    website: str
    score: int
    cover_letter: Optional[str] = None
    easy_apply: bool = False
    ai_status: AiStatus


class StatusUpdate(BaseModel):
    user_status: UserStatus
