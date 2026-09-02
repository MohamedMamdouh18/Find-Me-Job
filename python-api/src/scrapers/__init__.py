from .linkedin import fetch as linkedin_fetch
from .remoteok import fetch as remoteok_fetch

SOURCES = {
    "linkedin": linkedin_fetch,
    "remoteok": remoteok_fetch,
}

__all__ = ["SOURCES", "linkedin_fetch", "remoteok_fetch"]
