import importlib
from zoneinfo import ZoneInfo


def test_blank_env_vars_fallback(monkeypatch):
    monkeypatch.setenv("GENERIC_TIMEZONE", "")
    monkeypatch.setenv("SMTP_PORT", "")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("DELETE_OLD_JOBS_DAYS", "")
    monkeypatch.setenv("DB_PATH", "")

    import src.shared

    importlib.reload(src.shared)
    assert src.shared.TIMEZONE == ZoneInfo("UTC")
    assert src.shared.SMTP_PORT == 587
    assert src.shared.SMTP_HOST == "smtp.gmail.com"

    import src.database.core

    importlib.reload(src.database.core)
    assert src.database.core.DB == "/data/db/jobs.db"
