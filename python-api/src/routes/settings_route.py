from datetime import time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import Session

from ..database import get_session
from ..database.models.enums import PipelineMode
from ..database.repositories import FilteredJobRepository
from ..schemas.settings import NotificationTest, ScheduleUpdate
from ..services import notifications, schedule, settings, settings_store

settings_router = APIRouter(prefix="/api/settings", tags=["settings"])

TEST_NOTIFICATION = "Find Me a Job: test notification."

# How much of a stored secret the settings page may see. Enough to tell two keys
# apart, not enough to be the key — which is also why a value short enough for the
# hint to be most of it gets no hint at all rather than a complete one.
HINT_CHARS = 4
MIN_HINTABLE = HINT_CHARS * 2

# Request field -> registry key. The API speaks schedule, the table speaks keys.
FIELD_KEYS = {
    "enabled": "PIPELINE_ENABLED",
    "mode": "PIPELINE_MODE",
    "every_n_hours": "PIPELINE_EVERY_N_HOURS",
    "at_minute": "PIPELINE_AT_MINUTE",
    "at_time": "PIPELINE_AT_TIME",
    "retention_at_time": "RETENTION_AT_TIME",
}

# The three values a daily clash is made of. A request that leaves all three
# exactly where it found them cannot be the one that caused the clash.
CLASH_KEYS = ("PIPELINE_MODE", "PIPELINE_AT_TIME", "RETENTION_AT_TIME")


def _serialise(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, time):
        return value.strftime("%H:%M")
    return str(value)


def _jsonable(value) -> Any:
    """Parsed values go out as JSON natives; a clock goes out the way it came in."""
    return _serialise(value) if isinstance(value, time) else value


def _mask(raw: str) -> dict:
    if not raw:
        return {"set": False}
    return {"set": True, "hint": f"…{raw[-HINT_CHARS:]}" if len(raw) >= MIN_HINTABLE else ""}


@settings_router.get("")
def get_settings():
    """Effective values, secrets replaced by a hint.

    The API is unauthenticated and the tunnel exposes the dashboard publicly, so no
    endpoint may return a stored credential — the settings page would otherwise be a
    credential dump reachable by anyone holding the link.
    """
    out: dict[str, Any] = {}
    for key, spec in settings.SETTINGS.items():
        out[key] = _mask(settings.raw_setting(key)) if spec.secret else _jsonable(
            settings.get_setting(key)
        )
    return out


@settings_router.put("")
def update_settings(
    body: dict[str, Any] = Body(...), session: Session = Depends(get_session)
):
    """Partial update. Unknown keys are rejected rather than silently ignored."""
    updates: dict[str, str] = {}

    for key, value in body.items():
        if key not in settings.SETTINGS:
            raise HTTPException(status_code=400, detail=f"{key}: unknown setting")
        if key in settings.SCHEDULE_KEYS:
            raise HTTPException(
                status_code=400,
                detail=f"{key}: schedule keys are written through /api/settings/schedule,"
                " which validates the combination rather than each field",
            )

        spec = settings.SETTINGS[key]
        # None clears; a blank string on a secret means "leave it alone", because a
        # form round-trip cannot echo back a value it was never shown. Without that,
        # saving an unrelated field would wipe every credential on the page.
        raw = "" if value is None else _serialise(value)
        if spec.secret and value is not None and not raw:
            continue

        try:
            settings.parse_setting(key, raw)
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"{key}: {e}")
        updates[key] = raw

    if not updates:
        return {"updated": [], "reclassified": 0}

    # ai_status is written at scoring time, not derived on read, so moving the cutoff
    # would otherwise leave the table judged under two different rules at once.
    reclassified = 0
    if "FILTERING_SCORE" in updates:
        reclassified = FilteredJobRepository(session).reclassify(int(updates["FILTERING_SCORE"]))

    settings_store.save(session, updates)
    session.commit()
    settings_store.load_cache(session)
    return {"updated": sorted(updates), "reclassified": reclassified}


@settings_router.post("/notifications/test")
def test_notification(body: NotificationTest):
    """Posts a fixed message and reports the result: a silent notification channel
    is otherwise indistinguishable from a quiet night."""
    return notifications.send_test(body.channel, TEST_NOTIFICATION)


@settings_router.get("/schedule")
def get_schedule():
    return schedule.state()


@settings_router.put("/schedule")
def update_schedule(body: ScheduleUpdate, session: Session = Depends(get_session)):
    updates: dict[str, str] = {}
    for field, key in FIELD_KEYS.items():
        value = getattr(body, field)
        if value is None:
            continue
        raw = _serialise(value)
        try:
            settings.parse_setting(key, raw)
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"{field}: {e}")
        updates[key] = raw

    if not updates:
        return schedule.state()

    # Validate the combination, not just the fields: two individually valid times
    # can still put the pipeline on top of retention. Keys this request does not
    # write are read through get_setting, which falls back to the default on a bad
    # value: seed_from_env refuses to store an invalid env value but leaves it
    # readable, so parsing those keys strictly would let one typo in .env turn
    # every write into a 500 and strand the schedule at whatever it was.
    current = {key: settings.get_setting(key) for key in settings.SETTINGS}
    parsed = {
        **current,
        **{key: settings.parse_setting(key, raw) for key, raw in updates.items()},
    }
    conflict = schedule.conflict_message(schedule.SchedulePlan.from_parsed(parsed))
    # Only the daily/daily clash is rejectable — every interval that divides 24
    # includes midnight, so interval overlap is reported as a warning instead and
    # made harmless by the retention job taking the run lock. And only a clash
    # this request creates: the startup seed validates each key on its own, so
    # .env can install one, and rejecting writes that move none of the clashing
    # values would lock the user out of every way back out of it — including
    # turning the schedule off. A standing clash stays visible in state().
    # A disabled schedule has no pipeline job to collide with — apply_schedule()
    # removed it — so there is nothing to reject.
    creates_clash = any(parsed[key] != current[key] for key in CLASH_KEYS)
    if conflict and parsed["PIPELINE_ENABLED"] and parsed["PIPELINE_MODE"] == PipelineMode.DAILY and creates_clash:
        raise HTTPException(status_code=400, detail=f"{conflict} Pick a different time.")

    settings_store.save(session, updates)
    session.commit()
    settings_store.load_cache(session)
    schedule.apply_schedule()
    return schedule.state()
