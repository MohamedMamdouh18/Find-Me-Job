"""The notification fan-out.

One rule carries the file: a notification channel must never be able to fail a run,
so notify() swallows per channel and keeps going. The test button is the opposite —
it reports what happened, because a silent channel is otherwise indistinguishable
from a quiet night.
"""

import logging

import httpx
import pytest

from src.services import notifications, settings


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    # raw_setting falls back to the environment, and the test container is started
    # with the real .env, so a test that clears the cache would still find a token.
    for key in settings.SETTINGS:
        monkeypatch.delenv(key, raising=False)
    settings.set_cache(
        {
            "TELEGRAM_BOT_TOKEN": "123456789:AAtoken",
            "TELEGRAM_ID": "42",
            "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/abc",
        }
    )
    yield
    settings.set_cache({})


def _capture(monkeypatch, fail: str | None = None):
    posted: list[str] = []

    def fake_post(url, json=None, timeout=None):
        channel = "telegram" if "telegram" in url else "discord"
        if channel == fail:
            raise httpx.ConnectError("boom")
        posted.append(channel)
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(notifications.httpx, "post", fake_post)
    return posted


def test_notify_reaches_every_configured_channel(monkeypatch):
    posted = _capture(monkeypatch)

    notifications.notify("run finished")

    assert sorted(posted) == ["discord", "telegram"]


def test_a_dead_channel_does_not_stop_the_other_or_raise(monkeypatch):
    posted = _capture(monkeypatch, fail="telegram")

    notifications.notify("run finished")

    assert posted == ["discord"]


def test_an_unconfigured_channel_is_skipped(monkeypatch):
    settings.set_cache({"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/abc"})
    posted = _capture(monkeypatch)

    notifications.notify("run finished")

    assert posted == ["discord"]


def test_discord_messages_are_truncated_rather_than_rejected(monkeypatch):
    sent: list[dict] = []

    def fake_post(url, json=None, timeout=None):
        sent.append(json)
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(notifications.httpx, "post", fake_post)

    notifications._send_discord("x" * 5000)

    assert len(sent[0]["content"]) == notifications.DISCORD_LIMIT


def test_send_test_reports_the_result(monkeypatch):
    _capture(monkeypatch)

    assert notifications.send_test("telegram", "hi") == {
        "channel": "telegram",
        "ok": True,
        "status": 204,
        "error": None,
    }


def test_send_test_reports_a_failure_instead_of_swallowing_it(monkeypatch):
    _capture(monkeypatch, fail="discord")

    result = notifications.send_test("discord", "hi")

    assert result["ok"] is False
    assert "boom" in result["error"]


def test_send_test_says_when_a_channel_is_not_configured(monkeypatch):
    settings.set_cache({})
    _capture(monkeypatch)

    assert notifications.send_test("discord", "hi")["error"] == "not configured"


def test_send_test_rejects_an_unknown_channel():
    assert notifications.send_test("carrier-pigeon", "hi")["error"] == "unknown channel"


def _rejecting(monkeypatch, status: int = 401):
    def fake_post(url, json=None, timeout=None):
        return httpx.Response(status, request=httpx.Request("POST", url))

    monkeypatch.setattr(notifications.httpx, "post", fake_post)


def test_a_rejected_send_reports_the_status_not_the_credential(monkeypatch):
    """Both channels carry the credential in the request URL, and httpx writes that
    URL into the text of an HTTPStatusError. The error string is the body of
    POST /api/settings/notifications/test on an API nobody has to authenticate to."""
    _rejecting(monkeypatch)

    for channel, secret in (
        ("telegram", "123456789:AAtoken"),
        ("discord", "https://discord.com/api/webhooks/1/abc"),
    ):
        result = notifications.send_test(channel, "hi")

        assert result["ok"] is False
        assert secret not in result["error"]
        # Still useful to someone diagnosing a revoked token.
        assert "401" in result["error"]


def test_a_rejected_notify_does_not_log_the_credential(monkeypatch, caplog):
    _rejecting(monkeypatch)

    with caplog.at_level(logging.WARNING):
        notifications.notify("run finished")

    assert "123456789:AAtoken" not in caplog.text
    assert "webhooks/1/abc" not in caplog.text


def test_a_transport_error_is_scrubbed_of_the_credential(monkeypatch):
    """Not every failure is an HTTP status, and any of them may quote the URL."""

    def fake_post(url, json=None, timeout=None):
        raise httpx.ConnectError(f"cannot reach {url}")

    monkeypatch.setattr(notifications.httpx, "post", fake_post)

    error = notifications.send_test("discord", "hi")["error"]

    assert "https://discord.com/api/webhooks/1/abc" not in error
