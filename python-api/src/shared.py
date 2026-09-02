import asyncio
from datetime import datetime
import os
import httpx
import re
from zoneinfo import ZoneInfo
from .services.email_service import EmailService

CV_PATH = "/data/cv.docx"
PARAMS_DIR = "/data/params"
TIMEZONE = ZoneInfo(os.getenv("GENERIC_TIMEZONE") or "UTC")
DASHBOARD_URL = ""

TUNNEL_POLL_FAST = 5      # seconds, while the stack is starting
TUNNEL_POLL_SLOW = 60     # seconds, steady-state watch for a changed URL

EMAIL_SENDER_NAME = os.getenv("SENDER_NAME")
SMTP_HOST = os.getenv("SMTP_HOST") or "smtp.gmail.com"
# A blank SMTP_PORT= in .env yields "", not the default, and int("") is fatal at import.
SMTP_PORT = int(os.getenv("SMTP_PORT") or 587)
SMTP_USER = os.getenv("SMTP_USER")
SMTP_APP_PASSWORD = os.getenv("SMTP_APP_PASSWORD")


email_service = None

if SMTP_USER and SMTP_APP_PASSWORD:
    email_service = EmailService(
        host=SMTP_HOST,
        port=SMTP_PORT,
        user=SMTP_USER,
        password=SMTP_APP_PASSWORD,
        sender_name=EMAIL_SENDER_NAME,  # type: ignore
        cv_path=CV_PATH,
    )


from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler(timezone=TIMEZONE)


def send_telegram(message: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_ID")
    if not token or not chat_id:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=5,
        )
    except Exception as e:
        print(f"Telegram notification failed: {e}")


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
                print(f"Tunnel URL {'detected' if first else 'changed'}: {url}", flush=True)
                # send_telegram blocks on an HTTP call; off-thread so a slow or
                # unreachable Telegram cannot stall the event loop.
                await asyncio.to_thread(
                    send_telegram,
                    f"Find Me a Job is up!\n Dashboard: {url}"
                    if first
                    else f"Tunnel URL changed\n Dashboard: {url}",
                )

            attempt += 1
            # poll hard while the stack is coming up, then settle into a cheap watch
            await asyncio.sleep(TUNNEL_POLL_FAST if attempt < 30 else TUNNEL_POLL_SLOW)


def now():
    return datetime.now(TIMEZONE)
