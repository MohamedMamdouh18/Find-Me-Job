import asyncio
from datetime import datetime
import os
import httpx
import re
from zoneinfo import ZoneInfo

CV_PATH = "/data/cv.docx"
PARAMS_DIR = "/data/params"
TIMEZONE = ZoneInfo(os.getenv("GENERIC_TIMEZONE", "UTC"))
DASHBOARD_URL = ""


async def send_telegram(message: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_ID")
    if not token or not chat_id:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message},
                timeout=5,
            )
    except Exception as e:
        print(f"Telegram notification failed: {e}")


async def detect_tunnel_url_and_send_notification():
    global DASHBOARD_URL
    for _ in range(30):
        try:
            res = httpx.get("http://cloudflared:20241/metrics", timeout=2)
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", res.text)
            if match:
                DASHBOARD_URL = match.group(0)
                print(f"Tunnel URL detected: {DASHBOARD_URL}")
                await send_telegram(f"🚀 Find Me a Job is up!\n Dashboard: {DASHBOARD_URL}")
                return
        except Exception:
            pass
        await asyncio.sleep(5)
    print("Warning: Tunnel URL not detected")


def now():
    return datetime.now(TIMEZONE)
