from typing import Optional

from pydantic import BaseModel


class CompanyUpdate(BaseModel):
    """Every field optional: the dashboard sends only what changed.

    `starred` and `in_workflow` are separate on purpose — "I want to work here" and
    "scrape this every run" are different statements, and Phase 3 reads the first as a
    scoring signal.
    """

    careers_url: Optional[str] = None
    starred: Optional[bool] = None
    in_workflow: Optional[bool] = None
