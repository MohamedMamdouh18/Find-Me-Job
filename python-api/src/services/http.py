import logging
import time
import httpx

logger = logging.getLogger(__name__)


def get(
    url: str,
    *,
    timeout: float = 25.0,
    tries: int = 3,
    wait: float = 5.0,
    headers: dict | None = None,
) -> httpx.Response:
    """HTTP GET with bounded retry and exponential backoff."""
    req_headers = {"User-Agent": "Mozilla/5.0"}
    if headers:
        req_headers.update(headers)

    last_exc: Exception | None = None
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for attempt in range(1, tries + 1):
            try:
                res = client.get(url, headers=req_headers)
                if res.status_code == 200:
                    return res
                last_exc = RuntimeError(f"HTTP GET {url} returned {res.status_code}")
                logger.warning(f"GET {url} failed attempt {attempt}/{tries} (status {res.status_code})")
            except Exception as e:
                last_exc = e
                logger.warning(f"GET {url} attempt {attempt}/{tries} raised {e}")

            if attempt < tries:
                time.sleep(wait)

    raise RuntimeError(f"GET {url} failed after {tries} attempts: {last_exc}") from last_exc
