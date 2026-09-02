import json
import logging
import os
import re
import time
import urllib.parse
from bs4 import BeautifulSoup

from ..schemas.jobs import PendingJobRequest
from ..services.http import get
from ..services.run_context import RunContext
from ..shared import PARAMS_DIR

logger = logging.getLogger(__name__)


def build_linkedin_search_url(params: dict) -> str:
    """Builds a LinkedIn job search URL from a search config dict."""
    url = "https://www.linkedin.com/jobs/search/?"

    keyword = params.get("Keyword", "")
    location = params.get("Location", "")
    experience_level = params.get("Experience Level", "")
    remote = params.get("Remote", "")
    job_type = params.get("Job Type", "")
    easy_apply = params.get("Easy Apply", "")
    last_posted = params.get("Last Posted", "")

    if last_posted:
        url += f"f_TPR={last_posted}"
    if keyword:
        url += f"&keywords={urllib.parse.quote(keyword)}"
    if location:
        url += f"&location={urllib.parse.quote(location)}"
    if experience_level:
        exp_map = {
            "Internship": "1",
            "Entry level": "2",
            "Associate": "3",
            "Mid-Senior level": "4",
            "Director": "5",
            "Executive": "6",
        }
        exp_vals = [
            exp_map[e.strip()]
            for e in experience_level.split(",")
            if e.strip() in exp_map
        ]
        if exp_vals:
            url += f"&f_E={','.join(exp_vals)}"
    if remote:
        remote_map = {
            "On-Site": "1",
            "Remote": "2",
            "Hybrid": "3",
        }
        remote_vals = [
            remote_map[r.strip()]
            for r in remote.split(",")
            if r.strip() in remote_map
        ]
        if remote_vals:
            url += f"&f_WT={','.join(remote_vals)}"
    if job_type:
        jt_vals = [
            t.strip()[0].upper()
            for t in job_type.split(",")
            if t.strip()
        ]
        if jt_vals:
            url += f"&f_JT={','.join(jt_vals)}"
    if easy_apply:
        url += "&f_EA=true"

    return url


def parse_search_links(html: str) -> list[tuple[str, str]]:
    """Extracts (clean_url, link_job_id) pairs from LinkedIn search HTML.
    
    If no numeric job id matches, the item is dropped to avoid collapsing on undefined.
    """
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select("ul.jobs-search__results-list li a.base-card__full-link"):
        href = a.get("href")
        if not href:
            continue
        m = re.search(r"(\d+)\?", href) or re.search(r"(\d+)$", href)
        if not m:
            continue
        link_job_id = m.group(1)
        clean_url = href.split("?")[0]
        links.append((clean_url, link_job_id))
    return links


def parse_job_page(html: str, link_job_id: str) -> PendingJobRequest | None:
    """Extracts job fields from a LinkedIn job page."""
    soup = BeautifulSoup(html, "html.parser")

    title_elem = soup.select_one("div h1")
    company_elem = soup.select_one("div span a")
    loc_elem = soup.select_one(
        "div span[class*='topcard__flavor topcard__flavor--bullet']"
    )
    desc_elem = soup.select_one("div.description__text.description__text--rich")
    urn_elem = soup.select_one("a[data-item-type='semaphore']")

    title = title_elem.get_text(strip=True) if title_elem else ""
    company = company_elem.get_text(strip=True) if company_elem else ""
    location = loc_elem.get_text(strip=True) if loc_elem else ""

    if desc_elem:
        raw_desc = desc_elem.get_text(separator=" ", strip=True)
        description = re.sub(r"\s+", " ", raw_desc).strip()
    else:
        description = ""

    # URN segment is authoritative id
    urn_digits = None
    if urn_elem and urn_elem.get("data-semaphore-content-urn"):
        urn_val = urn_elem["data-semaphore-content-urn"]
        urn_last = urn_val.split(":")[-1]
        m = re.search(r"(\d+)", urn_last)
        if m:
            urn_digits = m.group(1)

    job_digits = urn_digits or link_job_id
    if not job_digits:
        return None

    easy_apply = "apply-button__offsite-apply-icon-svg" not in html
    applylink = f"https://www.linkedin.com/jobs/view/{job_digits}"

    return PendingJobRequest(
        id=f"linkedin_{job_digits}",
        title=title,
        company=company,
        location=location,
        applylink=applylink,
        description=description,
        website="LinkedIn",
        easy_apply=easy_apply,
    )


def fetch(ctx: RunContext, keywords: dict | None = None) -> list[PendingJobRequest]:
    """Scrapes LinkedIn searches. Note: ignores keywords parameter and reads params/linkedin_searches.txt."""
    searches_file = os.path.join(PARAMS_DIR, "linkedin_searches.txt")
    if not os.path.isfile(searches_file):
        logger.warning(f"LinkedIn searches file not found: {searches_file}")
        return []

    with open(searches_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    searches = data.get("searches", [])
    ctx.emit("scrape.linkedin.start", f"Starting LinkedIn scrape with {len(searches)} search criteria")

    collected_links: list[tuple[str, str]] = []
    seen_link_ids: set[str] = set()

    for idx, s in enumerate(searches, 1):
        search_url = build_linkedin_search_url(s)
        try:
            res = get(search_url, timeout=25.0, tries=3, wait=5.0)
            links = parse_search_links(res.text)
            for clean_url, jid in links:
                if jid not in seen_link_ids:
                    seen_link_ids.add(jid)
                    collected_links.append((clean_url, jid))
        except Exception as e:
            logger.warning(f"LinkedIn search {idx} failed: {e}")
            ctx.emit("scrape.linkedin.search_failed", f"Search {idx} failed: {e}", level="warning")

    total_links = len(collected_links)
    jobs: list[PendingJobRequest] = []

    for i, (job_url, link_job_id) in enumerate(collected_links, 1):
        ctx.emit(
            "scrape.linkedin.progress",
            f"Fetching LinkedIn job page {i}/{total_links}",
            detail=f"Page {i} of {total_links}",
            done=i,
            total=total_links,
        )
        time.sleep(1)
        try:
            res = get(job_url, timeout=20.0, tries=2, wait=3.0)
            job = parse_job_page(res.text, link_job_id)
            if job and job.title and job.description:
                jobs.append(job)
        except Exception as e:
            logger.warning(f"Failed to fetch LinkedIn job {job_url}: {e}")
            continue

    ctx.emit(
        "scrape.linkedin.done",
        f"Finished LinkedIn scrape. Found {len(jobs)} jobs",
        context={"found": len(jobs)},
    )
    return jobs
