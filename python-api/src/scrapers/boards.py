"""Parsers for the ATS boards a company can be fetched through.

None of these is a source. There is no cross-company endpoint for any ATS — every call
is per board token — so "scrape Greenhouse" is not an operation that exists; "fetch these
companies" is. See docs/adr/0001-a-company-is-the-source-not-an-ats.md.

Each parser is pure: payload plus the company row's label in, PendingJobRequest out. The
company name always comes from the row, never from the payload — Lever and Ashby carry
none at all, and Greenhouse's is only as right as whoever configured the board.

A payload of the wrong shape yields no jobs rather than raising. Boards answer an unknown
token in creative ways, including HTTP 200 with a marketing page, so a board is healthy
when it parses and yields rows, never because of a status code.
"""

import logging
from typing import Any

from .base import clean_description
from ..schemas.jobs import PendingJobRequest

logger = logging.getLogger(__name__)

GREENHOUSE = "greenhouse"
LEVER = "lever"
ASHBY = "ashby"

WEBSITE_LABELS = {GREENHOUSE: "Greenhouse", LEVER: "Lever", ASHBY: "Ashby"}

BOARD_URLS = {
    GREENHOUSE: "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
    LEVER: "https://api.lever.co/v0/postings/{token}?mode=json&limit=100",
    ASHBY: "https://api.ashbyhq.com/posting-api/job-board/{token}",
}


def _newest_first(rows: list[dict], *keys: str) -> list[dict]:
    """Sort a board's postings newest first.

    Load-bearing rather than cosmetic: the intake cap truncates, so whatever is at the
    front is what gets queued. Lever hands its postings back oldest-first, which without
    this means a company with more openings than the cap allows gets its stalest
    requisitions queued and its new ones dropped every night.

    Rows with no usable date sort last, because an unknown date is not a recent one.
    """
    def key(row: dict):
        for name in keys:
            value = row.get(name)
            if isinstance(value, (int, float)):
                return (1, str(value).zfill(20))
            if isinstance(value, str) and value:
                return (1, value)
        return (0, "")

    return sorted(rows, key=key, reverse=True)


def _rows(payload: Any, key: str | None) -> list[dict]:
    """The postings in a payload, or nothing at all when this is not the expected shape."""
    if key is None:
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get(key)
    else:
        rows = None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def parse_greenhouse(payload: Any, token: str, company: str) -> list[PendingJobRequest]:
    jobs = []
    for row in _newest_first(_rows(payload, "jobs"), "first_published", "updated_at"):
        job_id = row.get("id")
        title = row.get("title")
        if not job_id or not title:
            continue
        jobs.append(
            PendingJobRequest(
                id=f"greenhouse_{token}_{job_id}",
                title=title,
                company=company,
                location=(row.get("location") or {}).get("name") or "",
                applylink=row.get("absolute_url") or "",
                # content is entity-escaped HTML, so unescape before stripping.
                description=clean_description(row.get("content") or "", unescape_first=True),
                website=WEBSITE_LABELS[GREENHOUSE],
            )
        )
    return jobs


def _lever_description(row: dict) -> str:
    """descriptionPlain is roughly a third of the posting: the requirements and the
    benefits live in lists[] and additionalPlain, and a job scored without them is
    scored on the introduction alone."""
    parts = [row.get("descriptionPlain") or ""]
    for entry in row.get("lists") or []:
        if not isinstance(entry, dict):
            continue
        parts.append(entry.get("text") or "")
        parts.append(clean_description(entry.get("content") or ""))
    parts.append(row.get("additionalPlain") or "")
    return clean_description("\n".join(part for part in parts if part))


def parse_lever(payload: Any, token: str, company: str) -> list[PendingJobRequest]:
    jobs = []
    for row in _newest_first(_rows(payload, None), "createdAt"):
        job_id = row.get("id")
        title = row.get("text")
        if not job_id or not title:
            continue
        jobs.append(
            PendingJobRequest(
                id=f"lever_{token}_{job_id}",
                title=title,
                company=company,
                location=(row.get("categories") or {}).get("location") or "",
                applylink=row.get("hostedUrl") or row.get("applyUrl") or "",
                description=_lever_description(row),
                website=WEBSITE_LABELS[LEVER],
            )
        )
    return jobs


def parse_ashby(payload: Any, token: str, company: str) -> list[PendingJobRequest]:
    jobs = []
    for row in _newest_first(_rows(payload, "jobs"), "publishedAt"):
        job_id = row.get("id")
        title = row.get("title")
        if not job_id or not title or row.get("isListed") is False:
            continue
        jobs.append(
            PendingJobRequest(
                id=f"ashby_{token}_{job_id}",
                title=title,
                company=company,
                location=row.get("location") or "",
                applylink=row.get("jobUrl") or row.get("applyUrl") or "",
                description=clean_description(row.get("descriptionPlain") or ""),
                website=WEBSITE_LABELS[ASHBY],
            )
        )
    return jobs


PARSERS = {GREENHOUSE: parse_greenhouse, LEVER: parse_lever, ASHBY: parse_ashby}
