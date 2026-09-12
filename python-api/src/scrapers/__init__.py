from .base import Source
from .linkedin import fetch as linkedin_fetch
from .remoteok import fetch as remoteok_fetch

SOURCES: dict[str, Source] = {
    "linkedin": linkedin_fetch,
    "remoteok": remoteok_fetch,
}

__all__ = ["SOURCES", "Source", "linkedin_fetch", "remoteok_fetch"]
