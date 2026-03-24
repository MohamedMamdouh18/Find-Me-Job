from typing import Optional

from pydantic import BaseModel


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
    ai_status: str  # fit | not_fit


class StatusUpdate(BaseModel):
    user_status: str  # new | applied | wont_apply
