import requests

API = "http://python-api:8001/api"
TIMEOUT = 5


def get_stats() -> dict:
    try:
        return requests.get(f"{API}/jobs/stats", timeout=TIMEOUT).json()
    except Exception:
        return {
            "total": 0,
            "fit": 0,
            "not_fit": 0,
            "new": 0,
            "applied": 0,
            "wont_apply": 0,
            "avg_score": 0,
        }


def get_daily_applied(days: int = 7) -> list:
    try:
        return requests.get(
            f"{API}/jobs/stats/daily-applied", params={"days": days}, timeout=TIMEOUT
        ).json()
    except Exception:
        return []


def get_filter_options() -> dict:
    try:
        return requests.get(f"{API}/jobs/filtered/options", timeout=TIMEOUT).json()
    except Exception:
        return {"companies": [], "websites": []}


def get_filtered_jobs(
    ai_status: str | None,
    user_status: str | None,
    easy_apply: bool | None,
    min_score: int,
    search: str | None,
    company: str | None,
    website: str | None,
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
    try:
        return requests.get(f"{API}/jobs/filtered", params=params, timeout=TIMEOUT).json()
    except Exception:
        return {"rows": [], "total": 0, "pages": 1}


def update_job_status(job_id: str, user_status: str) -> bool:
    try:
        resp = requests.patch(
            f"{API}/jobs/filtered/{job_id}/status",
            json={"user_status": user_status},
            timeout=TIMEOUT,
        )
        return resp.status_code == 200
    except Exception:
        return False


def delete_job(job_id: str) -> bool:
    try:
        resp = requests.delete(f"{API}/jobs/filtered/{job_id}", timeout=TIMEOUT)
        return resp.status_code == 200
    except Exception:
        return False
