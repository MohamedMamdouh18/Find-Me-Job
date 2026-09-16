"""One fan-out for every run notification.

Call sites send run-shaped prose, never a job record, so both channels take plain
text and nothing here formats. Each channel is wrapped on its own: a dead webhook
logs a warning and the run carries on, because a notification channel must never
be able to fail a run.
"""

import logging

import httpx

from . import settings

logger = logging.getLogger(__name__)

TELEGRAM = "telegram"
DISCORD = "discord"

TIMEOUT = 5
# Discord's hard limit is 2000 characters and it rejects the whole post above it;
# a run summary can exceed that, so truncate rather than let the post 400.
DISCORD_LIMIT = 1900


class NotificationError(Exception):
    """A channel failure with the credential already taken out.

    Both channels carry their credential in the request URL — the Telegram token
    sits in the path and the Discord webhook URL is the whole credential — and
    httpx writes that URL into the text of an HTTPStatusError. Since a failure is
    logged by notify() and returned by send_test(), which is the body of an
    endpoint on an unauthenticated API behind a public tunnel, no raw exception
    may leave a sender. They translate here, where the secret is still in hand.
    """


def _failure(e: Exception, *secrets: str) -> NotificationError:
    # A status is the useful half of a wrong token and carries nothing else; every
    # other failure is reported by type with the known secrets scrubbed out.
    if isinstance(e, httpx.HTTPStatusError):
        return NotificationError(f"HTTP {e.response.status_code} {e.response.reason_phrase}".strip())
    text = f"{type(e).__name__}: {e}"
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return NotificationError(text)


def _send_telegram(message: str) -> int | None:
    token = settings.get_telegram_token()
    chat_id = settings.get_telegram_id()
    if not token or not chat_id:
        return None
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
    except Exception as e:
        # from None: the original carries the URL, and a traceback would print it.
        raise _failure(e, token) from None
    return response.status_code


def _send_discord(message: str) -> int | None:
    webhook_url = settings.get_discord_webhook_url()
    if not webhook_url:
        return None
    try:
        response = httpx.post(
            webhook_url,
            json={"content": message[:DISCORD_LIMIT]},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
    except Exception as e:
        raise _failure(e, webhook_url) from None
    return response.status_code


SENDERS = {TELEGRAM: _send_telegram, DISCORD: _send_discord}


def notify(message: str) -> None:
    """Send to every configured channel. Never raises."""
    for channel, send in SENDERS.items():
        try:
            send(message)
        except Exception as e:
            logger.warning(f"{channel} notification failed: {e}")


def send_test(channel: str, message: str) -> dict:
    """Used by the test button. Reports the result instead of swallowing it —
    a silent notification channel is indistinguishable from a quiet night."""
    send = SENDERS.get(channel)
    if send is None:
        return {"channel": channel, "ok": False, "status": None, "error": "unknown channel"}
    try:
        status = send(message)
    except Exception as e:
        return {"channel": channel, "ok": False, "status": None, "error": str(e)}
    if status is None:
        return {"channel": channel, "ok": False, "status": None, "error": "not configured"}
    return {"channel": channel, "ok": True, "status": status, "error": None}
