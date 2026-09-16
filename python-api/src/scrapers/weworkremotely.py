"""We Work Remotely — one RSS request, descriptions included.

The feed has no company element: the employer is glued to the front of the title as
"Company: Role". Splitting it is the whole parser, and getting it wrong means every job
carries a company name that is really a sentence.
"""

import logging
import re
import time
from xml.etree import ElementTree

from .base import clean_description
from ..schemas.jobs import PendingJobRequest
from ..services import settings
from ..services.http import get
from ..services.run_context import PauseRequested, RunContext

logger = logging.getLogger(__name__)

FEED = "https://weworkremotely.com/remote-jobs.rss"
CATEGORY_FEED = "https://weworkremotely.com/categories/{slug}.rss"
WEBSITE = "We Work Remotely"

# The site serves a Cloudflare interstitial when requests come too fast — HTTP 200, no
# items, "Just a moment…". A pause between categories keeps a five-category pick from
# looking like a scraper.
CATEGORY_PAUSE_SECONDS = 2


def _split_title(raw: str) -> tuple[str, str]:
    """"Acme Corp: Senior Engineer" -> ("Acme Corp", "Senior Engineer").

    Only the first colon splits, because role titles carry their own ("Engineer, Data:
    Platform"). A title with no colon has no company in it, so the company is left empty
    and the row is skipped rather than guessed at.
    """
    company, separator, title = raw.partition(":")
    if not separator:
        return "", raw.strip()
    return company.strip(), title.strip()


def parse_wwr(feed_text: str) -> list[PendingJobRequest]:
    try:
        root = ElementTree.fromstring(feed_text)
    except ElementTree.ParseError:
        return []

    jobs = []
    for item in root.iter("item"):
        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link).strip()
        company, title = _split_title(raw_title)
        if not guid or not title or not company:
            continue

        region = (item.findtext("region") or "").strip()
        jobs.append(
            PendingJobRequest(
                id=f"wwr_{re.sub(r'[^A-Za-z0-9_-]+', '_', guid)}",
                title=title,
                company=company,
                location=region or "Remote",
                applylink=link,
                description=clean_description(item.findtext("description") or ""),
                website=WEBSITE,
            )
        )
    return jobs


def _looks_challenged(text: str) -> bool:
    """A 200 with no items and no feed root is an interstitial, not an empty category.

    Reporting it as "0 jobs" would be the silent zero this phase exists to avoid: the
    category would look picked-over when it was never actually read.
    """
    return "<item>" not in text and "<rss" not in text.lower()


def fetch(ctx: RunContext, keywords: dict) -> list[PendingJobRequest]:
    categories = settings.get_wwr_categories()
    urls = (
        [(slug, CATEGORY_FEED.format(slug=slug)) for slug in categories]
        if categories
        else [("all jobs", FEED)]
    )
    ctx.emit(
        "scrape.wwr.start",
        f"Fetching We Work Remotely ({', '.join(name for name, _ in urls)})",
    )

    # Declared outside the loop: an interrupt part-way through returns what was gathered.
    collected: list[PendingJobRequest] = []
    seen_ids: set[str] = set()
    for index, (name, url) in enumerate(urls):
        try:
            if index:
                ctx.wait(CATEGORY_PAUSE_SECONDS)
            response = get(url, interrupt=ctx.interrupt)
            if _looks_challenged(response.text):
                ctx.emit(
                    f"scrape.wwr.{name}.blocked",
                    f"We Work Remotely served a challenge page for {name} rather than the "
                    "feed, so it was not read this run",
                    level="warning",
                )
                continue
            for job in parse_wwr(response.text):
                if job.id not in seen_ids:
                    seen_ids.add(job.id)
                    collected.append(job)
        except PauseRequested:
            ctx.emit(
                "scrape.wwr.interrupted",
                f"Interrupted with {len(collected)} jobs already gathered",
            )
            return collected
        except Exception as e:
            # Per category, so one failing feed does not cost the others.
            logger.warning(f"We Work Remotely {name} failed: {e}")
            ctx.emit(
                f"scrape.wwr.{name}.failed",
                f"We Work Remotely {name} failed: {e}",
                level="error",
            )

    ctx.emit(
        "scrape.wwr.done",
        f"We Work Remotely returned {len(collected)} jobs",
        context={"found": len(collected), "feeds": len(urls)},
    )
    return collected
