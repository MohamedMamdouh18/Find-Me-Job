import logging
import os
from dataclasses import dataclass
from datetime import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# bool("false") is True, so an explicit allowlist is the only safe read here:
# AUTO_EMAIL gates sending real applications to real employer addresses.
_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off", ""}

# Divisors of 24 only. */5 fires at 00, 05, 10, 15, 20 and then leaves a
# four-hour gap across midnight, which nobody means by "every 5 hours".
ALLOWED_INTERVAL_HOURS = (1, 2, 3, 4, 6, 8, 12)
# Mirrors PipelineMode in database/models/enums.py, which this module cannot
# import: shared.py imports settings at module scope, so reaching into the
# database package here closes an import loop. test_modes_match_the_enum pins
# the two together instead.
PIPELINE_MODES = ("interval", "daily")


def _parse_bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    raise ValueError(f"not a boolean: {raw!r}")


def _parse_mode(raw: str) -> str:
    value = raw.strip().lower()
    if value not in PIPELINE_MODES:
        raise ValueError(f"mode must be one of {PIPELINE_MODES}, got {raw!r}")
    return value


def _parse_interval_hours(raw: str) -> int:
    hours = int(raw)
    if hours not in ALLOWED_INTERVAL_HOURS:
        raise ValueError(f"interval must be one of {ALLOWED_INTERVAL_HOURS} hours, got {hours}")
    return hours


def _parse_minute(raw: str) -> int:
    minute = int(raw)
    if not 0 <= minute <= 59:
        raise ValueError(f"minute must be 0-59, got {minute}")
    return minute


def _parse_clock(raw: str) -> time:
    hour, _, minute = raw.strip().partition(":")
    parsed = time(int(hour), int(minute))
    return parsed


def _parse_text(raw: str) -> str:
    return raw.strip()


def _parse_score(raw: str) -> int:
    score = int(raw)
    if not 0 <= score <= 100:
        raise ValueError(f"score must be 0-100, got {score}")
    return score


def _parse_delay(raw: str) -> int:
    seconds = int(raw)
    if not 0 <= seconds <= 3600:
        raise ValueError(f"delay must be 0-3600 seconds, got {seconds}")
    return seconds


def _parse_retention_days(raw: str) -> int:
    days = int(raw)
    # 0 would mean "delete everything older than right now" on every retention
    # run, which empties the database nightly rather than disabling retention.
    if days < 1:
        raise ValueError(f"retention must be at least 1 day, got {days}")
    return days


def _parse_port(raw: str) -> int:
    port = int(raw)
    if not 1 <= port <= 65535:
        raise ValueError(f"port must be 1-65535, got {port}")
    return port


def _parse_url(raw: str) -> str:
    url = raw.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"must be an http(s) URL, got {raw!r}")
    return url


def _parse_optional_url(raw: str) -> str:
    """Blank is how a channel is turned off, so it is a value rather than an error."""
    url = raw.strip()
    return _parse_url(url) if url else ""


# ── User-editable settings ───────────────────────────────────────────────────
#
# Every key below can be stored in the app_settings table and edited from the
# dashboard: the row wins, then the env var, then the literal default. The table
# is untyped on purpose, so this registry is the only thing standing between a
# bad value and the scheduler — parse() both converts and validates, raising
# ValueError on anything invalid.
#
# secret=True keys are never returned by the API: it is unauthenticated and the
# tunnel exposes the dashboard publicly, so echoing a stored value would turn
# the settings page into a credential dump.


@dataclass(frozen=True)
class Setting:
    default: str
    parse: Callable[[str], Any]
    secret: bool = False


SETTINGS: dict[str, Setting] = {
    "PIPELINE_ENABLED": Setting("true", _parse_bool),
    "PIPELINE_MODE": Setting("daily", _parse_mode),
    "PIPELINE_EVERY_N_HOURS": Setting("6", _parse_interval_hours),
    "PIPELINE_AT_MINUTE": Setting("0", _parse_minute),
    "PIPELINE_AT_TIME": Setting("01:00", _parse_clock),
    # An hour clear of the pipeline default. That offset is now only a default:
    # the retention job takes the pipeline lock, so overlap is safe either way.
    "RETENTION_AT_TIME": Setting("00:00", _parse_clock),
    "LLM_URL": Setting(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", _parse_url
    ),
    "LLM_MODEL": Setting("gemini-2.5-flash", _parse_text),
    "LLM_API_KEY": Setting("", _parse_text, secret=True),
    "FILTERING_SCORE": Setting("60", _parse_score),
    "SCORING_DELAY_SECONDS": Setting("20", _parse_delay),
    "DELETE_OLD_JOBS_DAYS": Setting("60", _parse_retention_days),
    "AUTO_EMAIL": Setting("false", _parse_bool),
    "SENDER_NAME": Setting("", _parse_text),
    "SMTP_HOST": Setting("smtp.gmail.com", _parse_text),
    "SMTP_PORT": Setting("587", _parse_port),
    # Not a secret: it is a mailbox address, and the dashboard needs it to render
    # the cover letter footer.
    "SMTP_USER": Setting("", _parse_text),
    "SMTP_APP_PASSWORD": Setting("", _parse_text, secret=True),
    "TELEGRAM_ID": Setting("", _parse_text),
    "TELEGRAM_BOT_TOKEN": Setting("", _parse_text, secret=True),
    # The webhook URL is the whole credential: anyone holding it can post to the
    # channel, so it is masked like a token and redacted out of run events.
    "DISCORD_WEBHOOK_URL": Setting("", _parse_optional_url, secret=True),
}

# The six keys the typed schedule endpoint owns. It validates the combination,
# not just each field, so the generic endpoint refuses them: one writer per key.
SCHEDULE_KEYS = (
    "PIPELINE_ENABLED",
    "PIPELINE_MODE",
    "PIPELINE_EVERY_N_HOURS",
    "PIPELINE_AT_MINUTE",
    "PIPELINE_AT_TIME",
    "RETENTION_AT_TIME",
)

# Loaded from app_settings at startup and refreshed after every write. A process
# global for the same reason Progress is one: uvicorn runs a single worker.
_cache: dict[str, str] = {}


def set_cache(rows: dict[str, str]) -> None:
    """Rebinds rather than clear()+update(): a reader on another threadpool thread
    would otherwise see the empty dict between the two calls and fall back to env."""
    global _cache
    _cache = dict(rows)


def raw_setting(key: str) -> str:
    """Stored row, else env, else default.

    Membership, not truthiness, decides the first step: clearing a secret stores an
    empty row, and `or` would fall straight back to the env var the user was trying
    to get rid of. A blank env var still falls through to the default — `X=` in .env
    is a real case and int("") is fatal at import.
    """
    if key in _cache:
        return _cache[key]
    return os.getenv(key) or SETTINGS[key].default


def parse_setting(key: str, raw: str) -> Any:
    """Validate a candidate value. Raises ValueError, which callers turn into a 400."""
    return SETTINGS[key].parse(raw)


def get_setting(key: str) -> Any:
    """Parsed effective value. A stored value that no longer parses falls back to the
    default rather than killing the process — the scheduler must always come up."""
    spec = SETTINGS[key]
    raw = raw_setting(key)
    try:
        return spec.parse(raw)
    except (ValueError, TypeError):
        logger.warning("Invalid %s=%r; falling back to %r", key, raw, spec.default)
        return spec.parse(spec.default)


# ── Typed accessors ──────────────────────────────────────────────────────────
#
# Call sites use these rather than get_setting(KEY), so a key name lives in one
# place. Each reads at the point of use, which is what makes a settings change
# apply to the next run without a restart.


def get_llm_url() -> str:
    return get_setting("LLM_URL")


def get_llm_model() -> str:
    return get_setting("LLM_MODEL")


def get_llm_api_key() -> str:
    return get_setting("LLM_API_KEY")


def get_filtering_score() -> int:
    return get_setting("FILTERING_SCORE")


def get_auto_email() -> bool:
    return get_setting("AUTO_EMAIL")


def get_scoring_delay() -> int:
    return get_setting("SCORING_DELAY_SECONDS")


def get_delete_old_jobs_days() -> int:
    return get_setting("DELETE_OLD_JOBS_DAYS")


def get_sender_name() -> str:
    return get_setting("SENDER_NAME")


def get_smtp_host() -> str:
    return get_setting("SMTP_HOST")


def get_smtp_port() -> int:
    return get_setting("SMTP_PORT")


def get_smtp_user() -> str:
    return get_setting("SMTP_USER")


def get_smtp_password() -> str:
    return get_setting("SMTP_APP_PASSWORD")


def get_telegram_id() -> str:
    return get_setting("TELEGRAM_ID")


def get_telegram_token() -> str:
    return get_setting("TELEGRAM_BOT_TOKEN")


def get_discord_webhook_url() -> str:
    return get_setting("DISCORD_WEBHOOK_URL")
