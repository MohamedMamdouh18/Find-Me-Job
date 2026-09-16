"""Himalayas — a feed, cursor-paged, description already in the list response.

The feed offers six figures of jobs, so the source stops early rather than walking it:
the pipeline's intake gate caps what may be queued anyway, and pulling a hundred thousand
rows to discard almost all of them costs time nobody gets back. Paging ends at the first
page that yields nothing, or at the page budget below.
"""

import logging
from typing import Any

from .base import clean_description
from ..schemas.jobs import PendingJobRequest
from ..services.http import get
from ..services.run_context import PauseRequested, RunContext

logger = logging.getLogger(__name__)

API = "https://himalayas.app/jobs/api"
PAGE_SIZE = 100
# A ceiling on paging, not on jobs: the intake gate decides how many are queued. Six
# pages is enough to fill any sane per-source ceiling from the freshest end of the feed.
MAX_PAGES = 6
WEBSITE = "Himalayas"


def parse_himalayas(payload: Any) -> list[PendingJobRequest]:
    rows = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []

    jobs = []
    # Newest first: the intake cap truncates, so the front of this list is what gets queued.
    rows = sorted(
        (row for row in rows if isinstance(row, dict)),
        key=lambda row: row.get("pubDate") or 0,
        reverse=True,
    )
    for row in rows:
        if not isinstance(row, dict):
            continue
        guid = row.get("guid")
        title = row.get("title")
        company = row.get("companyName")
        if not guid or not title or not company:
            continue
        locations = row.get("locationRestrictions")
        jobs.append(
            PendingJobRequest(
                id=f"himalayas_{guid}",
                title=title,
                company=company,
                location=", ".join(locations) if isinstance(locations, list) else "Remote",
                applylink=row.get("applicationLink") or "",
                description=clean_description(row.get("description") or ""),
                website=WEBSITE,
            )
        )
    return jobs


def next_cursor(payload: Any) -> str | None:
    return payload.get("nextCursor") if isinstance(payload, dict) else None


def fetch(ctx: RunContext, keywords: dict) -> list[PendingJobRequest]:
    ctx.emit("scrape.himalayas.start", "Fetching Himalayas")
    # Declared outside the loop: an interrupt part-way through returns what was already
    # gathered, because a source only hands its jobs over on return and a resume does
    # not re-scrape.
    collected: list[PendingJobRequest] = []
    cursor = None

    try:
        for _ in range(MAX_PAGES):
            url = f"{API}?limit={PAGE_SIZE}" + (f"&cursor={cursor}" if cursor else "")
            payload = get(url, interrupt=ctx.interrupt).json()
            page = parse_himalayas(payload)
            if not page:
                break
            collected.extend(page)
            cursor = next_cursor(payload)
            if not cursor:
                break
    except PauseRequested:
        ctx.emit(
            "scrape.himalayas.interrupted",
            f"Interrupted with {len(collected)} jobs already gathered",
        )
        return collected
    except Exception as e:
        logger.warning(f"Himalayas scrape failed: {e}")
        ctx.emit("scrape.himalayas.failed", f"Himalayas scrape failed: {e}", level="error")
        return collected

    ctx.emit(
        "scrape.himalayas.done",
        f"Himalayas returned {len(collected)} jobs",
        context={"found": len(collected)},
    )
    return collected
