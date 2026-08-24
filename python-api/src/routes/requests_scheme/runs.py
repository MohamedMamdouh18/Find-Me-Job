from typing import Optional

from pydantic import BaseModel


class RunStart(BaseModel):
    trigger: str = "schedule"


class RunFinish(BaseModel):
    status: str = "success"
    error: Optional[str] = None
    jobs_scraped: Optional[int] = None
