import asyncio
from datetime import datetime
import logging
import os
import threading
import httpx
import re
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler

from .services import settings
from .services.email_service import EmailService
from .services.notifications import notify

logger = logging.getLogger(__name__)

CV_PATH = "/data/cv.docx"
PARAMS_DIR = "/data/params"
# Container wiring, not an application setting: the scheduler below is built with
# it at startup and the dashboard uses it as its own clock, so changing it at run
# time would change neither.
TIMEZONE = ZoneInfo(os.getenv("GENERIC_TIMEZONE") or "UTC")
DASHBOARD_URL = ""

TUNNEL_POLL_FAST = 5      # seconds, while the stack is starting
TUNNEL_POLL_SLOW = 60     # seconds, steady-state watch for a changed URL

scheduler = BackgroundScheduler(timezone=TIMEZONE)

# The SMTP account is editable from the dashboard, so the service cannot be built
# at import: it is rebuilt whenever the values it was built from change, and the
# open connection is reused whenever they have not. Callers must call this rather
# than hold the returned object — importing it by value is how a settings change
# fails to reach a call site.
_email_service: EmailService | None = None
_email_config: tuple | None = None
# Guards the swap only: two threads must not build two services, and the one being
# replaced must be quit exactly once. Tearing the connection down inside another
# thread's send is EmailService's own lock to prevent — this one is released before
# the caller sends, so it cannot. The import-time singleton this replaced could not
# race at all.
_email_lock = threading.Lock()


def get_email_service() -> EmailService | None:
    """The configured sender, or None when SMTP is not set up."""
    global _email_service, _email_config

    config = (
        settings.get_smtp_host(),
        settings.get_smtp_port(),
        settings.get_smtp_user(),
        settings.get_smtp_password(),
        settings.get_sender_name(),
    )
    host, port, user, password, sender_name = config

    with _email_lock:
        if not user or not password:
            _close_email_service()
            return None

        if _email_service is None or config != _email_config:
            _close_email_service()
            _email_service = EmailService(
                host=host,
                port=port,
                user=user,
                password=password,
                sender_name=sender_name,
                cv_path=CV_PATH,
            )
            _email_config = config

        return _email_service


def _close_email_service() -> None:
    """Caller holds _email_lock."""
    global _email_service, _email_config

    if _email_service is not None:
        try:
            _email_service.quit()
        except Exception as e:
            logger.warning(f"Closing the SMTP connection failed: {e}")
    _email_service = None
    _email_config = None


def close_email_service() -> None:
    with _email_lock:
        _close_email_service()


async def detect_tunnel_url_and_send_notification():
    """Track the cloudflared quick-tunnel URL for as long as the API runs.

    Two reasons this cannot be a one-shot poll:
      * cloudflared can fail for minutes (DNS, upstream outage) and only then
        succeed — the old version gave up after 150s and the dashboard's public
        link stayed dead until the API was restarted;
      * a quick tunnel gets a *new* hostname every time cloudflared restarts, so
        a URL captured once goes stale silently.
    """
    global DASHBOARD_URL

    async with httpx.AsyncClient(timeout=3) as client:
        attempt = 0
        while True:
            url = None
            try:
                res = await client.get("http://cloudflared:20241/metrics")
                match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", res.text)
                if match:
                    url = match.group(0)
            except Exception:
                pass

            if url and url != DASHBOARD_URL:
                first = not DASHBOARD_URL
                DASHBOARD_URL = url
                logger.info(f"Tunnel URL {'detected' if first else 'changed'}: {url}")
                # notify blocks on an HTTP call per channel; off-thread so a slow
                # or unreachable channel cannot stall the event loop.
                await asyncio.to_thread(
                    notify,
                    f"Find Me a Job is up!\n Dashboard: {url}"
                    if first
                    else f"Tunnel URL changed\n Dashboard: {url}",
                )

            attempt += 1
            # poll hard while the stack is coming up, then settle into a cheap watch
            await asyncio.sleep(TUNNEL_POLL_FAST if attempt < 30 else TUNNEL_POLL_SLOW)


def now():
    return datetime.now(TIMEZONE)
