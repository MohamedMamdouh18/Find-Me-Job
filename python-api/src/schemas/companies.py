from typing import Annotated, Optional
from urllib.parse import urlparse

from pydantic import AfterValidator, BaseModel, StringConstraints

# A blank name stored lowercase becomes a row nothing can match or display.
CompanyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _careers_url(value: Optional[str]) -> Optional[str]:
    """http(s) only, or blank to clear. The URL is fetched server-side and rendered
    as a link, so javascript:, file: and friends must not get in."""
    if not value:
        return value
    parsed = urlparse(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("careers_url must be an http(s) URL")
    return value.strip()


CareersUrl = Annotated[Optional[str], AfterValidator(_careers_url)]


class CompanyUpdate(BaseModel):
    """Every field optional: the dashboard sends only what changed.

    `starred` and `in_workflow` are separate on purpose — "I want to work here" and
    "scrape this every run" are different statements, and Phase 3 reads the first as a
    scoring signal.
    """

    careers_url: CareersUrl = None
    starred: Optional[bool] = None
    in_workflow: Optional[bool] = None
