import logging
import os
import uuid

import requests
from requests.adapters import HTTPAdapter

from constants import EMPTY_STATS

logger = logging.getLogger(__name__)

API = os.getenv("API_URL", "http://python-api:8001/api")
TIMEOUT = 5

# One pooled session for the whole app — a new TCP connection per widget
# interaction is pure latency on a page that reruns constantly.
_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=4, pool_maxsize=16, max_retries=1)
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)


def get_stats() -> dict:
    try:
        return _session.get(f"{API}/jobs/stats", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch job stats")
        return EMPTY_STATS.copy()


def get_daily_applied(days: int = 7) -> list:
    try:
        return _session.get(
            f"{API}/jobs/stats/daily-applied", params={"days": days}, timeout=TIMEOUT
        ).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch daily applied stats")
        return []


def get_score_distribution() -> list[dict]:
    """Pre-binned score histogram — the API does the bucketing, not the browser."""
    try:
        return _session.get(f"{API}/jobs/stats/score-distribution", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch score distribution")
        return []


def get_funnel() -> dict:
    """Arrivals per pipeline stage, counted from the status log."""
    try:
        return _session.get(f"{API}/jobs/stats/funnel", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch the funnel")
        return {"matched": 0, "applied": 0, "interviewing": 0, "offers": 0, "events": 0}


def get_top_companies(limit: int = 20) -> list[dict]:
    try:
        return _session.get(
            f"{API}/jobs/stats/top-companies", params={"limit": limit}, timeout=TIMEOUT
        ).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch top companies")
        return []


def get_stats_by_source() -> list:
    try:
        return _session.get(f"{API}/jobs/stats/by-source", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch stats by source")
        return []


def get_filter_options() -> dict:
    try:
        return _session.get(f"{API}/jobs/filtered/options", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch filter options")
        return {"companies": [], "websites": [], "locations": []}


def get_dashboard_public_url() -> str | None:
    try:
        resp = _session.get(f"{API}/params/dashboard-url", timeout=TIMEOUT)
        if resp.status_code != 200:
            return None
        url = resp.json().get("url", "")
        return url.strip() or None
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch dashboard public URL")
        return None


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
    max_score: int = 100,
    include_body: bool = False,
    include_keywords: bool = False,
) -> dict:
    params: dict = {
        "page": page,
        "page_size": page_size,
        "include_body": include_body,
        "include_keywords": include_keywords,
        "min_score": min_score,
        "max_score": max_score,
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
        return _session.get(f"{API}/jobs/filtered", params=params, timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch filtered jobs")
        return {"rows": [], "total": 0, "pages": 1}


def get_filtered_job(job_id: str) -> dict | None:
    """Fetch one job in full, including the description and application document."""
    try:
        resp = _session.get(f"{API}/jobs/filtered/{job_id}", timeout=TIMEOUT)
        if resp.status_code != 200:
            return None
        job = resp.json()
        return job if job and job.get("id") else None
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch job %s", job_id)
        return None


def get_job_match(job_id: str) -> dict:
    """Which CV skills the posting names. Keyword overlap, not the scorer's own
    reasoning — the scoring node returns a number and a cover letter, nothing else."""
    try:
        resp = _session.get(f"{API}/jobs/filtered/{job_id}/match", timeout=TIMEOUT)
        return resp.json() if resp.status_code == 200 else {}
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch match evidence for %s", job_id)
        return {}


def update_job_status(job_id: str, user_status: str) -> bool:
    try:
        resp = _session.patch(
            f"{API}/jobs/filtered/{job_id}/status",
            json={"user_status": user_status},
            timeout=TIMEOUT,
        )
        return resp.status_code == 200
    except (requests.RequestException, ValueError):
        logger.exception("Failed to update job %s status to %s", job_id, user_status)
        return False


def add_manual_job(
    title: str,
    company: str,
    location: str,
    applylink: str = "",
    website: str = "Manual",
    description: str = "Added manually via Dashboard",
    easy_apply: bool = False,
    user_status: str = "new",
) -> bool:
    """
    Sends a manually created job to the backend to be inserted directly into the
    FilteredJobs table, bypassing the scraping/pending queues.
    """
    try:
        job_data = {
            "id": f"manual-{uuid.uuid4()}",  # Generate a unique ID for manual entries
            "title": title,
            "company": company,
            "location": location,
            "applylink": applylink,
            "description": description,
            "website": website,
            "score": 100,  # Max score so manual jobs appear at the top
            "easy_apply": easy_apply,
            "user_status": user_status,  # Initial status chosen by the user
            "ai_status": "fit",  # Assumed fit since the user manually added it
        }
        resp = _session.post(f"{API}/jobs/filtered", json=job_data, timeout=TIMEOUT)
        return resp.status_code in (200, 201)
    except (requests.RequestException, ValueError):
        logger.exception("Failed to add manual job")
        return False


def delete_job(job_id: str) -> bool:
    try:
        resp = _session.delete(f"{API}/jobs/filtered/{job_id}", timeout=TIMEOUT)
        return resp.status_code == 200
    except (requests.RequestException, ValueError):
        logger.exception("Failed to delete job %s", job_id)
        return False


def get_job_history(job_id: str) -> list[dict]:
    try:
        return _session.get(f"{API}/jobs/filtered/{job_id}/history", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch history for %s", job_id)
        return []


# ---------------------------------------------------------------------------
# Starred companies
# ---------------------------------------------------------------------------


def get_starred_companies(search: str | None = None) -> list[dict]:
    try:
        params = {"search": search} if search else {}
        return _session.get(f"{API}/starred", params=params, timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch starred companies")
        return []


def get_starred_names() -> list[str]:
    """Return all starred company names (lowercase) for bulk client-side checks."""
    try:
        return _session.get(f"{API}/starred/names", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch starred company names")
        return []


def add_starred_company(
    company_name: str,
    careers_url: str | None = None,
    notes: str | None = None,
) -> dict | None:
    try:
        resp = _session.post(
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
        resp = _session.delete(f"{API}/starred/{id}", timeout=TIMEOUT)
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
        resp = _session.patch(
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
        resp = _session.post(
            f"{API}/starred/toggle",
            json={"company_name": company_name},
            timeout=TIMEOUT,
        )
        return resp.json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to toggle starred company %s", company_name)
        return {"is_starred": False}


# ---------------------------------------------------------------------------
# Blocked companies
# ---------------------------------------------------------------------------


def get_blocked_companies(search: str | None = None) -> list[dict]:
    try:
        params = {"search": search} if search else {}
        return _session.get(f"{API}/blocked", params=params, timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch blocked companies")
        return []


def get_blocked_names() -> list[str]:
    try:
        return _session.get(f"{API}/blocked/names", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch blocked company names")
        return []


def add_blocked_company(company_name: str, reason: str | None = None) -> dict | None:
    try:
        resp = _session.post(
            f"{API}/blocked",
            json={"company_name": company_name, "reason": reason},
            timeout=TIMEOUT,
        )
        return resp.json() if resp.status_code in (200, 201) else None
    except (requests.RequestException, ValueError):
        logger.exception("Failed to block company %s", company_name)
        return None


def delete_blocked_company(id: int) -> bool:
    try:
        return _session.delete(f"{API}/blocked/{id}", timeout=TIMEOUT).status_code == 200
    except (requests.RequestException, ValueError):
        logger.exception("Failed to unblock company %s", id)
        return False


def update_blocked_company(id: int, reason: str | None = None) -> bool:
    try:
        resp = _session.patch(f"{API}/blocked/{id}", json={"reason": reason}, timeout=TIMEOUT)
        return resp.status_code == 200
    except (requests.RequestException, ValueError):
        logger.exception("Failed to update blocked company %s", id)
        return False


def toggle_blocked_company(company_name: str) -> dict:
    try:
        return _session.post(
            f"{API}/blocked/toggle", json={"company_name": company_name}, timeout=TIMEOUT
        ).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to toggle blocked company %s", company_name)
        return {"is_blocked": False}


# ---------------------------------------------------------------------------
# Params, CV, runs, export, backup
# ---------------------------------------------------------------------------


def get_param(name: str) -> str | None:
    try:
        resp = _session.get(f"{API}/params/{name}", timeout=TIMEOUT)
        return resp.json().get("param") if resp.status_code == 200 else None
    except (requests.RequestException, ValueError):
        logger.exception("Failed to read param %s", name)
        return None


def put_param(name: str, content: str) -> tuple[bool, str]:
    try:
        resp = _session.put(f"{API}/params/{name}", json={"content": content}, timeout=TIMEOUT)
        if resp.status_code == 200:
            return True, "Saved"
        return False, _error_detail(resp)
    except (requests.RequestException, ValueError) as e:
        logger.exception("Failed to write param %s", name)
        return False, str(e)


def upload_cv(filename: str, data: bytes) -> tuple[bool, str]:
    try:
        resp = _session.post(
            f"{API}/cv/upload",
            files={
                "file": (
                    filename,
                    data,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            timeout=30,
        )
        if resp.status_code == 200:
            body = resp.json()
            return True, f"Uploaded {body['bytes']:,} bytes ({body['characters']:,} characters)"
        return False, _error_detail(resp)
    except (requests.RequestException, ValueError) as e:
        logger.exception("Failed to upload CV")
        return False, str(e)


def get_cv_keywords() -> dict:
    """The extracted titles/skills the scraper actually searches on."""
    try:
        return _session.get(f"{API}/cv/keywords", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch CV keywords")
        return {"keywords": None, "cv_hash": None, "updated_at": None}


def download_cv_file() -> bytes | None:
    try:
        resp = _session.get(f"{API}/cv/file", timeout=30)
        return resp.content if resp.status_code == 200 else None
    except requests.RequestException:
        logger.exception("Failed to download the CV")
        return None


def get_pending_count() -> int:
    try:
        return int(_session.get(f"{API}/jobs/pending/count", timeout=TIMEOUT).json()["count"])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        logger.exception("Failed to fetch the pending queue depth")
        return 0


def delete_all_jobs() -> tuple[bool, str]:
    try:
        resp = _session.delete(
            f"{API}/jobs/filtered", params={"confirm": "delete-all-jobs"}, timeout=60
        )
        if resp.status_code == 200:
            return True, f"Deleted {resp.json().get('deleted', 0)} jobs."
        return False, _error_detail(resp)
    except (requests.RequestException, ValueError) as e:
        logger.exception("Failed to clear the jobs table")
        return False, str(e)


def get_cv_info() -> dict:
    try:
        return _session.get(f"{API}/cv/info", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch CV info")
        return {"exists": False}


def get_runs(limit: int = 20) -> list[dict]:
    try:
        return _session.get(f"{API}/runs", params={"limit": limit}, timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch run history")
        return []


def export_jobs(
    fmt: str = "csv", include_body: bool = False, ai_status: str | None = None
) -> bytes | None:
    params: dict = {"format": fmt, "include_body": include_body}
    if ai_status:
        params["ai_status"] = ai_status
    try:
        resp = _session.get(f"{API}/jobs/export", params=params, timeout=120)
        return resp.content if resp.status_code == 200 else None
    except requests.RequestException:
        logger.exception("Failed to export jobs")
        return None


def download_backup() -> bytes | None:
    try:
        resp = _session.get(f"{API}/backup", timeout=120)
        return resp.content if resp.status_code == 200 else None
    except requests.RequestException:
        logger.exception("Failed to download backup")
        return None


def _error_detail(resp) -> str:
    try:
        return str(resp.json().get("detail", resp.text))[:300]
    except ValueError:
        return f"HTTP {resp.status_code}"


def trigger_run() -> tuple[bool, str]:
    """POST to /api/runs/trigger to start the python pipeline in the background."""
    try:
        resp = _session.post(f"{API}/runs/trigger", timeout=10)
        if resp.status_code in (200, 201, 202):
            return True, "Run triggered."
        return False, _error_detail(resp)
    except requests.RequestException as e:
        return False, f"Could not reach API: {e}"



def get_current_run() -> dict | None:
    """Fetch live in-process progress and countdown from /api/runs/current."""
    try:
        resp = _session.get(f"{API}/runs/current", timeout=TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        return None
    except (requests.RequestException, ValueError):
        return None


def get_run_events(run_id: int) -> list[dict]:
    """Fetch event history and failure payloads for a specific run."""
    try:
        return _session.get(f"{API}/runs/{run_id}/events", timeout=TIMEOUT).json()
    except (requests.RequestException, ValueError):
        logger.exception("Failed to fetch events for run %s", run_id)
        return []
