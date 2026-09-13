from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..database import get_session
from ..database.models.enums import PipelineMode
from ..schemas.settings import ScheduleUpdate
from ..services import schedule, settings, settings_store

settings_router = APIRouter(prefix="/api/settings", tags=["settings"])

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
    return str(value)


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
