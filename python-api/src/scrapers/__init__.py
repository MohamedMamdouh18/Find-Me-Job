from .base import Source
from .linkedin import fetch as linkedin_fetch
from .remoteok import fetch as remoteok_fetch

SOURCES: dict[str, Source] = {
    "linkedin": linkedin_fetch,
    "remoteok": remoteok_fetch,
}

# How each source is named in the dashboard. Registered alongside SOURCES so a new
# module arrives with its own label rather than a title-cased key.
SOURCE_LABELS: dict[str, str] = {
    "linkedin": "LinkedIn",
    "remoteok": "RemoteOK",
}

__all__ = ["SOURCES", "SOURCE_LABELS", "Source", "linkedin_fetch", "remoteok_fetch"]
