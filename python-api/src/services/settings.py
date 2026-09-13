import logging
import os
from dataclasses import dataclass
from datetime import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


def get_llm_url() -> str:
    return (
        os.getenv("LLM_URL")
        or "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )


def get_llm_model() -> str:
    return os.getenv("LLM_MODEL") or "gemini-2.5-flash"


def get_llm_api_key() -> str:
    return os.getenv("LLM_API_KEY") or ""


def get_filtering_score() -> int:
    return int(os.getenv("FILTERING_SCORE") or 60)


# bool("false") is True, so an explicit allowlist is the only safe read here:
# this flag gates sending real applications to real employer addresses.
_TRUTHY = {"1", "true", "yes", "on"}


def get_auto_email() -> bool:
    return os.getenv("AUTO_EMAIL", "").strip().lower() in _TRUTHY


def get_scoring_delay() -> int:
    return int(os.getenv("SCORING_DELAY_SECONDS") or 20)


def get_delete_old_jobs_days() -> int:
    return int(os.getenv("DELETE_OLD_JOBS_DAYS") or 60)


def get_sender_name() -> str:
    return os.getenv("SENDER_NAME") or ""


# ── User-editable settings ───────────────────────────────────────────────────
#
# Everything above reads .env directly. Everything below can also be stored in
# the app_settings table and edited from the dashboard: the row wins, then the
# env var, then the literal default. The table is untyped on purpose, so this
# registry is the only thing standing between a bad value and the scheduler —
# parse() both converts and validates, raising ValueError on anything invalid.

# Divisors of 24 only. */5 fires at 00, 05, 10, 15, 20 and then leaves a
# four-hour gap across midnight, which nobody means by "every 5 hours".
ALLOWED_INTERVAL_HOURS = (1, 2, 3, 4, 6, 8, 12)
# Mirrors PipelineMode in database/models/enums.py, which this module cannot
# import: shared.py imports settings at module scope, so reaching into the
# database package here closes an import loop. test_modes_match_the_enum pins
# the two together instead.
PIPELINE_MODES = ("interval", "daily")

_FALSY = {"0", "false", "no", "off", ""}


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


@dataclass(frozen=True)
class Setting:
    default: str
    parse: Callable[[str], Any]


SETTINGS: dict[str, Setting] = {
    "PIPELINE_ENABLED": Setting("true", _parse_bool),
    "PIPELINE_MODE": Setting("daily", _parse_mode),
    "PIPELINE_EVERY_N_HOURS": Setting("6", _parse_interval_hours),
    "PIPELINE_AT_MINUTE": Setting("0", _parse_minute),
    "PIPELINE_AT_TIME": Setting("01:00", _parse_clock),
    # An hour clear of the pipeline default. That offset is now only a default:
    # the retention job takes the pipeline lock, so overlap is safe either way.
    "RETENTION_AT_TIME": Setting("00:00", _parse_clock),
}

# Loaded from app_settings at startup and refreshed after every write. A process
# global for the same reason Progress is one: uvicorn runs a single worker.
_cache: dict[str, str] = {}


def set_cache(rows: dict[str, str]) -> None:
    """Rebinds rather than clear()+update(): a reader on another threadpool thread
    would otherwise see the empty dict between the two calls and fall back to env."""
    global _cache
    _cache = dict(rows)


def raw_setting(key: str) -> str:
    """Stored row, else env, else default — the .env idiom used above, one level deeper."""
    return _cache.get(key) or os.getenv(key) or SETTINGS[key].default


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

