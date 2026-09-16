"""A blank `X=` in .env yields "", not the default, and int("") is fatal.

The keys that survive as environment reads are container wiring; the rest are
seeds for app_settings and fall back through the registry, so both paths are
checked here.
"""

import importlib
from zoneinfo import ZoneInfo

import pytest

from src.services import settings


@pytest.fixture(autouse=True)
def clean_cache():
    settings.set_cache({})
    yield
    settings.set_cache({})


def test_blank_env_vars_fallback(monkeypatch):
    monkeypatch.setenv("GENERIC_TIMEZONE", "")
    monkeypatch.setenv("SMTP_PORT", "")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("DELETE_OLD_JOBS_DAYS", "")
    monkeypatch.setenv("SCORING_DELAY_SECONDS", "")
    monkeypatch.setenv("FILTERING_SCORE", "")
    monkeypatch.setenv("DB_PATH", "")

    import src.shared

    importlib.reload(src.shared)
    assert src.shared.TIMEZONE == ZoneInfo("UTC")

    # Same guard one level deeper: these are settings now, so the fallback happens
    # in the registry rather than at import.
    assert settings.get_smtp_port() == 587
    assert settings.get_smtp_host() == "smtp.gmail.com"
    assert settings.get_delete_old_jobs_days() == 60
    assert settings.get_scoring_delay() == 20
    assert settings.get_filtering_score() == 60

    import src.database.core

    importlib.reload(src.database.core)
    assert src.database.core.DB == "/data/db/jobs.db"
