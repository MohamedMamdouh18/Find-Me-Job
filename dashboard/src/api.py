import logging

import requests

from constants import EMPTY_STATS

logger = logging.getLogger(__name__)

API = "http://python-api:8001/api"
TIMEOUT = 5


def get_stats() -> dict:
    try:
        return requests.get(f"{API}/jobs/stats", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch job stats")
        return EMPTY_STATS.copy()


def get_daily_applied(days: int = 7) -> list:
    try:
        return requests.get(
            f"{API}/jobs/stats/daily-applied", params={"days": days}, timeout=TIMEOUT
        ).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch daily applied stats")
        return []


def get_scores() -> list[int]:
    try:
        return requests.get(f"{API}/jobs/stats/scores", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch scores")
        return []


def get_stats_by_source() -> list:
    try:
        return requests.get(f"{API}/jobs/stats/by-source", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch stats by source")
        return []


def get_filter_options() -> dict:
    try:
        return requests.get(f"{API}/jobs/filtered/options", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch filter options")
        return {"companies": [], "websites": [], "locations": []}


def get_filtered_jobs(
    ai_status: str | None,
    user_status: str | None,
    easy_apply: bool | None,
    min_score: int,
    search: str | None,
    company: str | None,
    website: str | None,
    location: str | None,
    starred_only: bool,
    sort_by: str,
    sort_order: str,
    page: int,
    page_size: int,
) -> dict:
    params: dict = {
        "page": page,
        "page_size": page_size,
        "min_score": min_score,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }
    if ai_status:
        params["ai_status"] = ai_status
    if user_status:
        params["user_status"] = user_status
    if easy_apply is not None:
        params["easy_apply"] = easy_apply
    if search:
        params["search"] = search
    if company:
        params["company"] = company
    if website:
        params["website"] = website
    if location:
        params["location"] = location
    if starred_only:
        params["starred_only"] = True
    try:
        return requests.get(f"{API}/jobs/filtered", params=params, timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch filtered jobs")
        return {"rows": [], "total": 0, "pages": 1}


def update_job_status(job_id: str, user_status: str) -> bool:
    try:
        resp = requests.patch(
            f"{API}/jobs/filtered/{job_id}/status",
            json={"user_status": user_status},
            timeout=TIMEOUT,
        )
        return resp.status_code == 200
    except (requests.RequestException, ValueError):
        logger.exception("Failed to update job %s status to %s", job_id, user_status)
        return False


def delete_job(job_id: str) -> bool:
    try:
        resp = requests.delete(f"{API}/jobs/filtered/{job_id}", timeout=TIMEOUT)
        return resp.status_code == 200
    except (requests.RequestException, ValueError):
        logger.exception("Failed to delete job %s", job_id)
        return False


def get_job_history(job_id: str) -> list[dict]:
    try:
        return requests.get(
            f"{API}/jobs/filtered/{job_id}/history", timeout=TIMEOUT
        ).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch history for %s", job_id)
        return []


# ---------------------------------------------------------------------------
# Starred companies
# ---------------------------------------------------------------------------

def get_starred_companies(search: str | None = None) -> list[dict]:
    try:
        params = {"search": search} if search else {}
        return requests.get(f"{API}/starred", params=params, timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch starred companies")
        return []


def get_starred_names() -> list[str]:
    """Return all starred company names (lowercase) for bulk client-side checks."""
    try:
        return requests.get(f"{API}/starred/names", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch starred company names")
        return []


def add_starred_company(
    company_name: str,
    careers_url: str | None = None,
    notes: str | None = None,
) -> dict | None:
    try:
        resp = requests.post(
            f"{API}/starred",
            json={"company_name": company_name, "careers_url": careers_url, "notes": notes},
            timeout=TIMEOUT,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        return None
    except (requests.RequestException, ValueError):
        logger.exception("Failed to add starred company %s", company_name)
        return None


def delete_starred_company(id: int) -> bool:
    try:
        resp = requests.delete(f"{API}/starred/{id}", timeout=TIMEOUT)
        return resp.status_code == 200
    except (requests.RequestException, ValueError):
        logger.exception("Failed to delete starred company %s", id)
        return False


def update_starred_company(
    id: int,
    careers_url: str | None = None,
    notes: str | None = None,
) -> bool:
    try:
        resp = requests.patch(
            f"{API}/starred/{id}",
            json={"careers_url": careers_url, "notes": notes},
            timeout=TIMEOUT,
        )
        return resp.status_code == 200
    except (requests.RequestException, ValueError):
        logger.exception("Failed to update starred company %s", id)
        return False


def toggle_starred_company(company_name: str) -> dict:
    try:
        resp = requests.post(
            f"{API}/starred/toggle",
            json={"company_name": company_name},
            timeout=TIMEOUT,
        )
        return resp.json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to toggle starred company %s", company_name)
        return {"is_starred": False}
