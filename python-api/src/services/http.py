import logging
import threading
import time
import httpx

from . import net_abort
from .run_context import PauseRequested

logger = logging.getLogger(__name__)


def get(
    url: str,
    *,
    timeout: float = 25.0,
    tries: int = 3,
    wait: float = 5.0,
    headers: dict | None = None,
    interrupt: threading.Event | None = None,
) -> httpx.Response:
    """HTTP GET with bounded retry and exponential backoff.

    `interrupt` is the run's pause/stop event. Scraping a single LinkedIn search can
    sit here for tries x timeout plus the backoff, so without this a stop requested
    during the scrape phase waits minutes. Registering the client also lets a stop
    kill the read outright rather than waiting for the timeout.
    """
    req_headers = {"User-Agent": "Mozilla/5.0"}
    if headers:
        req_headers.update(headers)

    last_exc: Exception | None = None
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        net_abort.register(client)
        try:
            for attempt in range(1, tries + 1):
                if interrupt is not None and interrupt.is_set():
                    raise PauseRequested("run interrupted before HTTP GET")
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
                    # Doubling per attempt, as the docstring promises: a scraper that
                    # is being rate limited should back off, not hammer at a fixed
                    # interval. Waiting on the event lets a stop cut the backoff short.
                    backoff = wait * (2 ** (attempt - 1))
                    if interrupt is not None:
                        interrupt.wait(backoff)
                    else:
                        time.sleep(backoff)
        finally:
            net_abort.unregister(client)

    if interrupt is not None and interrupt.is_set():
        raise PauseRequested("run interrupted during the final HTTP GET")

    raise RuntimeError(f"GET {url} failed after {tries} attempts: {last_exc}") from last_exc
