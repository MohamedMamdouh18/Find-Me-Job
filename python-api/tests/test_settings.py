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


# ── the registry as a whole ──────────────────────────────────────────────────
#
# The table is untyped, so parse() is the only thing between a bad value and the
# scheduler. These cover the registry directly; the endpoints that write it are
# covered in test_settings_api.py.


@pytest.fixture(autouse=True)
def clean_cache():
    settings.set_cache({})
    yield
    settings.set_cache({})


@pytest.mark.parametrize("key", list(settings.SETTINGS))
def test_every_key_has_a_parseable_default(monkeypatch, key):
    monkeypatch.delenv(key, raising=False)
    assert settings.get_setting(key) == settings.parse_setting(key, settings.SETTINGS[key].default)


def test_secret_keys_are_exactly_the_credentials():
    secrets = {key for key, spec in settings.SETTINGS.items() if spec.secret}
    assert secrets == {
        "LLM_API_KEY",
        "SMTP_APP_PASSWORD",
        "TELEGRAM_BOT_TOKEN",
        "DISCORD_WEBHOOK_URL",
    }
    # A mailbox address, not a credential: the dashboard renders it on the PDF.
    assert settings.SETTINGS["SMTP_USER"].secret is False


def test_precedence_is_row_then_env_then_default(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert settings.get_llm_model() == "gemini-2.5-flash"

    monkeypatch.setenv("LLM_MODEL", "from-env")
    assert settings.get_llm_model() == "from-env"

    settings.set_cache({"LLM_MODEL": "from-row"})
    assert settings.get_llm_model() == "from-row"


def test_a_cleared_row_wins_over_the_environment(monkeypatch):
    """Clearing a secret stores an empty row; falling back to env there would
    resurrect the value the user just removed."""
    monkeypatch.setenv("LLM_API_KEY", "from-env")
    settings.set_cache({"LLM_API_KEY": ""})
    assert settings.get_llm_api_key() == ""


@pytest.mark.parametrize(
    "key,raw",
    [
        ("FILTERING_SCORE", "101"),
        ("FILTERING_SCORE", "-1"),
        ("FILTERING_SCORE", "sixty"),
        ("SCORING_DELAY_SECONDS", "-1"),
        ("SCORING_DELAY_SECONDS", "3601"),
        ("DELETE_OLD_JOBS_DAYS", "0"),
        ("SMTP_PORT", "0"),
        ("SMTP_PORT", "70000"),
        ("LLM_URL", "ftp://example.test"),
        ("LLM_URL", "example.test/v1"),
        ("DISCORD_WEBHOOK_URL", "not-a-url"),
        ("AUTO_EMAIL", "maybe"),
    ],
)
def test_parsers_reject_bad_values(key, raw):
    with pytest.raises(ValueError):
        settings.parse_setting(key, raw)


def test_a_blank_webhook_is_off_rather_than_invalid():
    assert settings.parse_setting("DISCORD_WEBHOOK_URL", "") == ""


def test_an_unparseable_stored_value_falls_back_instead_of_raising(monkeypatch):
    """The scheduler must always come up, so a row that no longer parses is a
    warning and a default, not a dead container."""
    monkeypatch.delenv("SMTP_PORT", raising=False)
    settings.set_cache({"SMTP_PORT": "not-a-port"})
    assert settings.get_smtp_port() == 587


def test_schedule_keys_match_the_typed_endpoint():
    """The generic PUT refuses these so there is one writer per key; if the typed
    endpoint grows a field, this is what notices."""
    from src.routes.settings_route import FIELD_KEYS

    assert set(settings.SCHEDULE_KEYS) == set(FIELD_KEYS.values())
