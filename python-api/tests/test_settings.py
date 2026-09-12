"""Env parsing in services/settings.py.

AUTO_EMAIL gates sending real application emails to real employer addresses, so a
value the user reads as "off" must never parse as on.
"""

import pytest

from src.services import settings


@pytest.mark.parametrize(
    "raw",
    ["false", "False", "FALSE", "0", "no", "off", "", "   ", "nonsense"],
)
def test_auto_email_off_for_falsey_values(monkeypatch, raw):
    monkeypatch.setenv("AUTO_EMAIL", raw)
    assert settings.get_auto_email() is False


@pytest.mark.parametrize("raw", ["1", "true", "True", "TRUE", "yes", "on", " true "])
def test_auto_email_on_for_truthy_values(monkeypatch, raw):
    monkeypatch.setenv("AUTO_EMAIL", raw)
    assert settings.get_auto_email() is True


def test_auto_email_off_when_unset(monkeypatch):
    monkeypatch.delenv("AUTO_EMAIL", raising=False)
    assert settings.get_auto_email() is False


@pytest.mark.parametrize(
    "getter,env,default",
    [
        (settings.get_filtering_score, "FILTERING_SCORE", 60),
        (settings.get_scoring_delay, "SCORING_DELAY_SECONDS", 20),
        (settings.get_delete_old_jobs_days, "DELETE_OLD_JOBS_DAYS", 60),
    ],
)
def test_int_settings_fall_back_on_blank(monkeypatch, getter, env, default):
    """A blank `X=` in .env is a real case; int("") would be fatal."""
    monkeypatch.setenv(env, "")
    assert getter() == default


@pytest.mark.parametrize(
    "getter,env,default",
    [
        (settings.get_llm_model, "LLM_MODEL", "gemini-2.5-flash"),
        (settings.get_llm_api_key, "LLM_API_KEY", ""),
        (settings.get_sender_name, "SENDER_NAME", ""),
    ],
)
def test_str_settings_fall_back_on_blank(monkeypatch, getter, env, default):
    monkeypatch.setenv(env, "")
    assert getter() == default
