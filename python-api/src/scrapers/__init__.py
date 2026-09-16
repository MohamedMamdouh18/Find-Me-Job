from .base import Source
from .companies import fetch as companies_fetch
from .himalayas import fetch as himalayas_fetch
from .linkedin import fetch as linkedin_fetch
from .remoteok import fetch as remoteok_fetch
from .weworkremotely import fetch as wwr_fetch

COMPANIES = "companies"

SOURCES: dict[str, Source] = {
    COMPANIES: companies_fetch,
    "linkedin": linkedin_fetch,
    "remoteok": remoteok_fetch,
    "himalayas": himalayas_fetch,
    "weworkremotely": wwr_fetch,
}

# Sources whose output goes through the relevance filter: the ones that carry the whole
# world rather than something the user asked for by name. LinkedIn is absent on purpose —
# its searches are written by the user, so they are explicit intent in the same way a
# company row is, and filtering them again would drop jobs the user's own query asked for.
FILTERED_SOURCES = {"remoteok", "himalayas", "weworkremotely"}

# How each source is named in the dashboard. Registered alongside SOURCES so a new
# module arrives with its own label rather than a title-cased key.
SOURCE_LABELS: dict[str, str] = {
    COMPANIES: "Company boards",
    "linkedin": "LinkedIn",
    "remoteok": "RemoteOK",
    "himalayas": "Himalayas",
    "weworkremotely": "We Work Remotely",
}

__all__ = [
    "SOURCES",
    "SOURCE_LABELS",
    "FILTERED_SOURCES",
    "COMPANIES",
    "Source",
]
