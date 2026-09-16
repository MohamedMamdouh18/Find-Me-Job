"""The company source: one walk over the company list, one fetch per employer.

There is no cross-company endpoint for any ATS, so this is the only shape a board fetch
can take — see docs/adr/0001-a-company-is-the-source-not-an-ats.md. Greenhouse, Lever and
Ashby are fetch methods on a row here, not sources of their own.

Detection is a sniff rather than a URL match, because a careers subdomain is very often a
board wearing a company domain. It has three real outcomes and one waiting state, and the
waiting state matters: "not checked yet" is not "cannot be read", and a switch that can be
turned on for the latter is a switch that lies.
"""

import hashlib
import json
import logging
import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .base import clean_description
from .boards import ASHBY, BOARD_URLS, GREENHOUSE, LEVER, PARSERS
from ..schemas.jobs import PendingJobRequest
from ..services.http import get
from ..services.identity import normalise
from ..services.run_context import PauseRequested, RunContext

logger = logging.getLogger(__name__)

UNKNOWN = "unknown"
ATS = "ats"
PAGE = "page"
UNREADABLE = "unreadable"

# Board hosts, as they appear in a careers URL or in a link on one.
URL_PATTERNS = [
    (GREENHOUSE, re.compile(r"(?:job-)?boards\.greenhouse\.io/([A-Za-z0-9_-]+)")),
    (GREENHOUSE, re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)")),
    (LEVER, re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)")),
    (ASHBY, re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_-]+)")),
]

# Fingerprints of an embedded board, for pages that do not link their ATS outright.
EMBED_PATTERNS = [
    (GREENHOUSE, re.compile(r"grnhse_app|greenhouse\.io/embed", re.IGNORECASE)),
    (LEVER, re.compile(r"lever\.co/embed|data-lever", re.IGNORECASE)),
    (ASHBY, re.compile(r"ashbyhq\.com/[^\"']*embed", re.IGNORECASE)),
]

JSONLD = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def detect_from_url(url: str) -> tuple[str | None, str | None]:
    """The cheap pass: a URL that points straight at a board names its own token."""
    for ats, pattern in URL_PATTERNS:
        found = pattern.search(url or "")
        if found:
            return ats, found.group(1)
    return None, None


def detect_from_html(html: str, page_url: str) -> tuple[str | None, str | None]:
    """The sniff: what is actually behind this page.

    A link or iframe to a board host carries the token with it, which is the case worth
    catching — careers.acme.com is very often a Greenhouse board on a company domain.
    An embed script proves the ATS without naming the token, which is not enough to fetch
    a board, so that falls back to reading the page.
    """
    ats, token = detect_from_url(html or "")
    if ats and token:
        return ats, token
    for ats, pattern in EMBED_PATTERNS:
        if pattern.search(html or ""):
            return ats, None
    return None, None


def _jsonld_location(entry: dict) -> str:
    location = entry.get("jobLocation")
    if isinstance(location, list):
        location = location[0] if location else None
    if isinstance(location, dict):
        address = location.get("address")
        if isinstance(address, dict):
            parts = [address.get("addressLocality"), address.get("addressCountry")]
            joined = ", ".join(part for part in parts if isinstance(part, str))
            if joined:
                return joined
    return "Not specified"


def jsonld_jobs(html: str, company: str, page_url: str) -> list[PendingJobRequest]:
    """Postings from the structured data a careers page publishes for search engines.

    This is the whole of the page path. Anything less structured is left unread rather
    than guessed at, and the stripped page is never handed to an LLM: that is the one
    rung that can invent a job, which then costs a scoring call, a cover letter and a
    slot in the table while looking exactly like a real one.
    """
    slug = normalise(company).replace(" ", "-")
    jobs: list[PendingJobRequest] = []
    for blob in JSONLD.findall(html or ""):
        try:
            data = json.loads(blob.strip())
        except (ValueError, TypeError):
            continue
        for entry in data if isinstance(data, list) else [data]:
            if not isinstance(entry, dict) or entry.get("@type") != "JobPosting":
                continue
            title = entry.get("title")
            if not title:
                continue
            url = entry.get("url") or page_url
            jobs.append(
                PendingJobRequest(
                    # sha256, not hash(): the builtin is salted per process, so every
                    # restart would re-id the same posting and seen_jobs would never
                    # recognise it again.
                    id=f"company_{slug}_{hashlib.sha256(f'{url}{title}'.encode()).hexdigest()[:16]}",
                    title=title,
                    company=company,
                    location=_jsonld_location(entry),
                    applylink=url,
                    description=clean_description(
                        entry.get("description") or "", unescape_first=True
                    ),
                    website=company,
                )
            )
    return jobs


def robots_allows(url: str, interrupt=None) -> bool:
    """Whether the site asks us not to read this path.

    Checked before any page fetch. A disallowed listing path is a reason to say so on the
    row, not a thing to engineer around. It does not apply to the ATS APIs, which are
    documented public endpoints meant to be called.
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    try:
        response = get(
            f"{parsed.scheme}://{parsed.netloc}/robots.txt", tries=1, interrupt=interrupt
        )
        if response.status_code >= 400:
            return True  # no robots file is permission, by convention
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser.can_fetch("*", url)
    except PauseRequested:
        raise
    except Exception:
        # An unreachable robots file is not consent, but it is not a refusal we can prove
        # either. Allowing it keeps one flaky request from making a good company dead.
        return True


def detect(url: str, interrupt=None) -> dict:
    """Work out how this company can be fetched. Returns the row's verdict."""
    ats, token = detect_from_url(url)
    if ats and token:
        return {"fetch_method": ATS, "ats": ats, "ats_token": token, "fetch_note": None}

    if not robots_allows(url, interrupt=interrupt):
        return {
            "fetch_method": UNREADABLE,
            "ats": None,
            "ats_token": None,
            "fetch_note": "The site's robots.txt asks us not to read this page.",
        }

    try:
        html = get(url, tries=1, interrupt=interrupt).text
    except PauseRequested:
        raise
    except Exception as e:
        return {
            "fetch_method": UNREADABLE,
            "ats": None,
            "ats_token": None,
            "fetch_note": f"The page could not be fetched: {e}",
        }

    ats, token = detect_from_html(html, url)
    if ats and token:
        return {"fetch_method": ATS, "ats": ats, "ats_token": token, "fetch_note": None}

    if jsonld_jobs(html, "probe", url):
        return {"fetch_method": PAGE, "ats": None, "ats_token": None, "fetch_note": None}

    return {
        "fetch_method": UNREADABLE,
        "ats": None,
        "ats_token": None,
        "fetch_note": (
            "No job board and no structured job data on this page — its listings are "
            "probably rendered in the browser."
        ),
    }


def fetch_company(company, interrupt=None) -> list[PendingJobRequest]:
    """One company's open roles.

    The unit both callers share: the source wraps it in the per-row loop, and the
    on-demand endpoint calls it directly, because the Source protocol takes a run context
    and "scrape now" has no run.
    """
    label = (company.company_name or "").title()

    if company.fetch_method == ATS and company.ats in PARSERS and company.ats_token:
        url = BOARD_URLS[company.ats].format(token=company.ats_token)
        payload = get(url, interrupt=interrupt).json()
        # Parsed, never trusted by status: a board answers an unknown token in creative
        # ways, including 200 with its own marketing page.
        return PARSERS[company.ats](payload, token=company.ats_token, company=label)

    if company.fetch_method == PAGE and company.careers_url:
        html = get(company.careers_url, interrupt=interrupt).text
        return jsonld_jobs(html, label, company.careers_url)

    return []


def fetch(ctx: RunContext, keywords: dict) -> list[PendingJobRequest]:
    """Every company marked for the workflow, one request each."""
    from ..database.repositories.companies import CompanyRepository

    repo = CompanyRepository(ctx.session)
    rows = repo.in_workflow()
    ctx.emit("scrape.companies.start", f"Fetching {len(rows)} companies")

    collected: list[PendingJobRequest] = []
    for company in rows:
        if ctx.interrupt is not None and ctx.interrupt.is_set():
            ctx.emit(
                "scrape.companies.interrupted",
                f"Interrupted with {len(collected)} jobs already gathered",
            )
            return collected
        try:
            jobs = fetch_company(company, interrupt=ctx.interrupt)
        except PauseRequested:
            ctx.emit(
                "scrape.companies.interrupted",
                f"Interrupted with {len(collected)} jobs already gathered",
            )
            return collected
        except Exception as e:
            # Isolated per company, not per source: a dead token must not cost the other
            # twenty-four companies their nightly fetch.
            #
            # Deliberately NOT record_fetch(0): a failure is not an empty board. Counting
            # it as one would let two flaky nights turn a healthy company `unreadable`
            # and switch it off, with a note claiming it returned no jobs.
            logger.warning(f"Company {company.company_name} failed: {e}")
            ctx.emit(
                f"scrape.companies.{company.company_name}.failed",
                f"{company.company_name} failed: {e}",
                level="error",
            )
            continue

        # As in the on-demand route: a row that made no request has not returned nothing.
        if company.fetch_method in (ATS, PAGE):
            repo.record_fetch(company, len(jobs))
        if not jobs:
            ctx.emit(
                f"scrape.companies.{company.company_name}.empty",
                f"{company.company_name} returned no jobs",
                level="warning",
            )
        collected.extend(jobs)

    # No commit here: a source must not write, and the pipeline commits per job as it
    # saves. These row updates ride along with the first of those.
    ctx.emit(
        "scrape.companies.done",
        f"Companies returned {len(collected)} jobs",
        context={"found": len(collected)},
    )
    return collected
