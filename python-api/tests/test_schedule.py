"""The user-configurable schedule: registry validation, trigger shape, and the
retention/pipeline mutual exclusion.

The settings table is untyped, so the registry in services/settings.py is the only
thing between a bad value and the scheduler — most of this file guards that edge.
"""

import threading
import time as time_module
from datetime import datetime, time, timedelta

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool

import src.database.models  # noqa: F401
from src.database.core import get_session
from src.database.repositories import AppSettingRepository
from src.main import app
from src.services import pipeline as pipeline_module
from src.services import schedule, settings, settings_store
from src.shared import TIMEZONE


@pytest.fixture(autouse=True)
def clean_cache():
    settings.set_cache({})
    yield
    settings.set_cache({})


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def client(engine):
    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _next_fires(trigger, count, start):
    """The times a trigger would actually fire, which is what we care about."""
    fires, previous, cursor = [], None, start
    for _ in range(count):
        fire = trigger.get_next_fire_time(previous, cursor)
        fires.append(fire)
        previous, cursor = fire, fire + timedelta(seconds=1)
    return fires


# ── registry validation ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "key,raw",
    [
        ("PIPELINE_MODE", "hourly"),
        ("PIPELINE_EVERY_N_HOURS", "5"),  # not a divisor of 24
        ("PIPELINE_EVERY_N_HOURS", "0"),
        ("PIPELINE_EVERY_N_HOURS", "24"),
        ("PIPELINE_AT_MINUTE", "60"),
        ("PIPELINE_AT_MINUTE", "-1"),
        ("PIPELINE_AT_TIME", "25:00"),
        ("PIPELINE_AT_TIME", "0100"),
        ("PIPELINE_AT_TIME", ""),
        ("PIPELINE_ENABLED", "maybe"),
    ],
)
def test_invalid_values_are_rejected(key, raw):
    with pytest.raises((ValueError, TypeError)):
        settings.parse_setting(key, raw)


def test_stored_garbage_falls_back_to_default_instead_of_crashing():
    """A bad row must never stop the scheduler coming up."""
    settings.set_cache({"PIPELINE_EVERY_N_HOURS": "5"})
    assert settings.get_setting("PIPELINE_EVERY_N_HOURS") == 6


def test_precedence_is_row_then_env_then_default(monkeypatch):
    monkeypatch.setenv("PIPELINE_AT_TIME", "07:30")
    assert settings.get_setting("PIPELINE_AT_TIME") == time(7, 30)

    settings.set_cache({"PIPELINE_AT_TIME": "09:15"})
    assert settings.get_setting("PIPELINE_AT_TIME") == time(9, 15)

    settings.set_cache({})
    monkeypatch.delenv("PIPELINE_AT_TIME")
    assert settings.get_setting("PIPELINE_AT_TIME") == time(1, 0)


def test_defaults_reproduce_the_previous_hardcoded_schedule(monkeypatch):
    for key in settings.SETTINGS:
        monkeypatch.delenv(key, raising=False)
    assert settings.get_setting("PIPELINE_AT_TIME") == time(1, 0)
    assert settings.get_setting("RETENTION_AT_TIME") == time(0, 0)
    assert settings.get_setting("PIPELINE_MODE") == "daily"
    assert settings.get_setting("PIPELINE_ENABLED") is True


# ── triggers ────────────────────────────────────────────────────────────────


def test_interval_mode_is_wall_clock_anchored_not_boot_anchored():
    settings.set_cache(
        {
            "PIPELINE_MODE": "interval",
            "PIPELINE_EVERY_N_HOURS": "3",
            "PIPELINE_AT_MINUTE": "15",
        }
    )
    start = datetime(2026, 9, 13, 14, 37, tzinfo=TIMEZONE)
    fires = _next_fires(schedule.pipeline_trigger(), 4, start)

    assert [f.hour for f in fires] == [15, 18, 21, 0]
    assert {f.minute for f in fires} == {15}


def test_daily_mode_fires_once_a_day_at_the_set_time():
    settings.set_cache({"PIPELINE_MODE": "daily", "PIPELINE_AT_TIME": "09:30"})
    start = datetime(2026, 9, 13, 0, 0, tzinfo=TIMEZONE)
    fires = _next_fires(schedule.pipeline_trigger(), 3, start)

    assert [(f.hour, f.minute) for f in fires] == [(9, 30)] * 3
    assert [f.day for f in fires] == [13, 14, 15]


# ── collision between the two jobs ──────────────────────────────────────────


def test_daily_clash_is_detected():
    assert schedule.conflict_message(schedule.SchedulePlan("daily", time(0, 0), 6, 0, time(0, 0)))


def test_daily_at_a_different_time_is_clean():
    assert schedule.conflict_message(schedule.SchedulePlan("daily", time(1, 0), 6, 0, time(0, 0))) is None


def test_every_interval_that_divides_24_hits_midnight():
    """This is why validation cannot be the safety mechanism."""
    for hours in settings.ALLOWED_INTERVAL_HOURS:
        assert schedule.conflict_message(schedule.SchedulePlan("interval", time(1, 0), hours, 0, time(0, 0)))


def test_interval_off_the_retention_minute_is_clean():
    assert schedule.conflict_message(schedule.SchedulePlan("interval", time(1, 0), 3, 30, time(0, 0))) is None


def test_retention_skips_while_a_run_holds_the_lock(monkeypatch):
    calls = []
    monkeypatch.setattr(schedule, "delete_old_jobs", lambda: calls.append("deleted"))

    assert pipeline_module.try_acquire_lock_for_retention()
    try:
        schedule._retention_job()
        assert calls == [], "retention deleted rows during a run"
    finally:
        pipeline_module.release_run_lock()

    schedule._retention_job()
    assert calls == ["deleted"]


def test_retention_releases_the_lock_even_when_it_raises(monkeypatch):
    def boom():
        raise RuntimeError("delete failed")

    monkeypatch.setattr(schedule, "delete_old_jobs", boom)
    with pytest.raises(RuntimeError):
        schedule._retention_job()

    assert pipeline_module.try_acquire_lock_for_retention(), "lock leaked after a failed retention"
    pipeline_module.release_run_lock()


# ── applying the schedule ───────────────────────────────────────────────────


def test_enabling_and_disabling_adds_and_removes_only_the_pipeline_job(monkeypatch):
    sched = BackgroundScheduler(timezone=TIMEZONE)
    monkeypatch.setattr(schedule, "scheduler", sched)
    sched.start(paused=True)
    try:
        settings.set_cache({"PIPELINE_ENABLED": "true"})
        schedule.apply_schedule()
        assert sched.get_job(schedule.PIPELINE_JOB_ID) is not None
        assert sched.get_job(schedule.RETENTION_JOB_ID) is not None

        settings.set_cache({"PIPELINE_ENABLED": "false"})
        schedule.apply_schedule()
        assert sched.get_job(schedule.PIPELINE_JOB_ID) is None
        # Retention is never disabled by the pipeline toggle.
        assert sched.get_job(schedule.RETENTION_JOB_ID) is not None
    finally:
        sched.shutdown(wait=False)


def test_missed_fires_get_an_hour_of_grace(monkeypatch):
    sched = BackgroundScheduler(timezone=TIMEZONE)
    monkeypatch.setattr(schedule, "scheduler", sched)
    sched.start(paused=True)
    try:
        schedule.apply_schedule()
        job = sched.get_job(schedule.PIPELINE_JOB_ID)
        assert job.misfire_grace_time == schedule.MISFIRE_GRACE_SECONDS
        assert job.coalesce is True
        assert job.max_instances == 1
    finally:
        sched.shutdown(wait=False)


# ── seeding ─────────────────────────────────────────────────────────────────


def test_seed_fills_missing_rows_only_and_ignores_invalid_env(monkeypatch, engine):
    monkeypatch.setenv("PIPELINE_MODE", "interval")
    monkeypatch.setenv("PIPELINE_EVERY_N_HOURS", "99")  # invalid: must not be stored

    with Session(engine) as session:
        AppSettingRepository(session).set("PIPELINE_AT_TIME", "05:00")
        session.commit()

        settings_store.seed_from_env(session)
        session.commit()
        rows = AppSettingRepository(session).get_all()

    assert rows["PIPELINE_MODE"] == "interval"
    assert "PIPELINE_EVERY_N_HOURS" not in rows
    assert rows["PIPELINE_AT_TIME"] == "05:00", "seed overwrote an existing row"


def test_seed_is_idempotent(monkeypatch, engine):
    monkeypatch.setenv("PIPELINE_MODE", "interval")
    with Session(engine) as session:
        first = settings_store.seed_from_env(session)
        session.commit()
        second = settings_store.seed_from_env(session)
        session.commit()

    assert first >= 1
    assert second == 0


# ── API ─────────────────────────────────────────────────────────────────────


def test_put_rejects_an_invalid_value(client):
    res = client.put("/api/settings/schedule", json={"mode": "hourly"})
    assert res.status_code == 400
    assert "mode" in res.json()["detail"]


def test_put_rejects_a_five_hour_interval(client):
    res = client.put("/api/settings/schedule", json={"every_n_hours": 5})
    assert res.status_code == 400


def test_put_persists_and_applies(client, engine):
    res = client.put(
        "/api/settings/schedule",
        json={"mode": "interval", "every_n_hours": 3, "at_minute": 30},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "interval"
    assert body["every_n_hours"] == 3
    assert body["description"] == "Every 3h at :30"

    with Session(engine) as session:
        stored = AppSettingRepository(session).get_all()
    assert stored["PIPELINE_MODE"] == "interval"
    assert stored["PIPELINE_EVERY_N_HOURS"] == "3"


def test_put_rejects_a_daily_clash_with_retention(client):
    res = client.put(
        "/api/settings/schedule",
        json={"mode": "daily", "at_time": "00:00", "retention_at_time": "00:00"},
    )
    assert res.status_code == 400


def test_put_rejects_moving_the_pipeline_onto_retention(client, monkeypatch):
    """A clash already in place is no licence to create a second one."""
    monkeypatch.setenv("PIPELINE_AT_TIME", "00:00")
    monkeypatch.setenv("RETENTION_AT_TIME", "00:00")
    res = client.put("/api/settings/schedule", json={"mode": "daily", "at_time": "05:00"})
    assert res.status_code == 200

    res = client.put(
        "/api/settings/schedule",
        json={"mode": "daily", "at_time": "05:00", "retention_at_time": "05:00"},
    )
    assert res.status_code == 400


def test_a_seeded_clash_does_not_block_disabling(client, engine, monkeypatch):
    """Boot validates each key alone, so .env can install the clash the PUT rejects.

    Refusing every later write would leave the user locked out of the one control
    that makes the clash moot, which is turning the schedule off.
    """
    monkeypatch.setenv("PIPELINE_AT_TIME", "00:00")
    monkeypatch.setenv("RETENTION_AT_TIME", "00:00")
    with Session(engine) as session:
        settings_store.seed_from_env(session)
        session.commit()
        settings_store.load_cache(session)

    res = client.put("/api/settings/schedule", json={"enabled": False})
    assert res.status_code == 200
    assert res.json()["enabled"] is False


def test_a_standing_clash_does_not_block_an_unrelated_write(client, monkeypatch):
    """The dashboard sends every field, so a clash must be judged on what changed."""
    monkeypatch.setenv("PIPELINE_AT_TIME", "00:00")
    monkeypatch.setenv("RETENTION_AT_TIME", "00:00")
    res = client.put(
        "/api/settings/schedule",
        json={
            "enabled": False,
            "mode": "daily",
            "at_time": "00:00",
            "retention_at_time": "00:00",
        },
    )
    assert res.status_code == 200
    assert res.json()["conflict"], "the clash is still reported, just not enforced"


def test_an_invalid_env_value_does_not_block_writing_another_key(client, monkeypatch):
    """seed_from_env refuses to store a bad env value but leaves it readable, so the
    PUT path has to fall back like every other reader rather than 500."""
    monkeypatch.setenv("PIPELINE_MODE", "hourly")
    res = client.put("/api/settings/schedule", json={"enabled": False})
    assert res.status_code == 200
    assert res.json()["enabled"] is False
    assert res.json()["mode"] == "daily", "bad value should read as the default"


def test_interval_overlap_is_a_warning_not_an_error(client):
    """Rejecting this would forbid every legal interval, since they all hit midnight."""
    res = client.put(
        "/api/settings/schedule",
        json={
            "mode": "interval",
            "every_n_hours": 3,
            "at_minute": 0,
            "retention_at_time": "00:00",
        },
    )
    assert res.status_code == 200
    assert res.json()["conflict"]


def test_disabling_reports_manual_only(client):
    res = client.put("/api/settings/schedule", json={"enabled": False})
    assert res.status_code == 200
    assert res.json()["enabled"] is False
    assert res.json()["description"] == "Manual only"


def test_manual_trigger_still_works_with_the_schedule_off(client):
    client.put("/api/settings/schedule", json={"enabled": False})
    assert client.post("/api/runs/trigger").status_code == 202


# ── the pipeline/retention lock handoff ─────────────────────────────────────


def _hold_as_retention_for(seconds: float) -> threading.Thread:
    """Retention holding the lock the way _retention_job does, then letting go."""
    assert pipeline_module.try_acquire_lock_for_retention()

    def worker():
        time_module.sleep(seconds)
        pipeline_module.release_run_lock()

    thread = threading.Thread(target=worker)
    thread.start()
    return thread


def test_a_run_waits_for_retention_instead_of_being_dropped():
    """The fire is consumed, not missed, so coalesce and misfire_grace_time cannot
    recover it — skipping here loses a whole night of scraping silently."""
    thread = _hold_as_retention_for(0.4)
    try:
        started = time_module.monotonic()
        acquired, reason = pipeline_module._acquire_for_pipeline()
        waited = time_module.monotonic() - started
    finally:
        thread.join()

    assert acquired, f"scheduled run dropped while retention held the lock: {reason}"
    assert waited >= 0.3, "did not actually wait for retention"
    pipeline_module.release_run_lock()


def test_a_second_run_still_skips_immediately():
    """The concurrency rule max_instances=1 relies on: runs never queue behind runs."""
    assert pipeline_module._acquire_for_pipeline()[0]
    try:
        started = time_module.monotonic()
        acquired, reason = pipeline_module._acquire_for_pipeline()
        waited = time_module.monotonic() - started
    finally:
        pipeline_module.release_run_lock()

    assert not acquired
    assert reason == "a run is already in progress"
    assert waited < 0.2, "a second run waited instead of skipping"


def test_a_run_gives_up_if_retention_never_finishes(monkeypatch):
    monkeypatch.setattr(pipeline_module, "RETENTION_WAIT_SECONDS", 0.5)
    thread = _hold_as_retention_for(2.0)
    try:
        acquired, reason = pipeline_module._acquire_for_pipeline()
        assert not acquired
        assert "retention still running" in reason
    finally:
        thread.join()


def test_the_lock_holder_is_cleared_after_a_run():
    assert pipeline_module._acquire_for_pipeline()[0]
    pipeline_module.release_run_lock()
    assert pipeline_module._lock_holder is None
    # Still claimable by retention, so the next cycle is not wedged.
    assert pipeline_module.try_acquire_lock_for_retention()
    pipeline_module.release_run_lock()


class _HandoverLock:
    """A lock that is released by its holder between the caller's first failed
    acquire and its read of _lock_holder — the handover window that made a
    scheduled run skip while the lock was actually free."""

    def __init__(self):
        self.calls = 0
        self._real = threading.Lock()

    def acquire(self, blocking=True, timeout=-1):
        self.calls += 1
        if self.calls == 1:
            # Held at this instant, and the holder clears itself right after.
            pipeline_module._lock_holder = None
            return False
        return self._real.acquire(blocking, timeout) if blocking else self._real.acquire(False)

    def release(self):
        self._real.release()


def test_a_run_is_not_dropped_during_a_lock_handover(monkeypatch):
    """None means in-transition, never held-by-a-run: a failed acquire already
    proved the lock was held, so treating None as a run drops a real fire."""
    fake = _HandoverLock()
    monkeypatch.setattr(pipeline_module, "_run_lock", fake)
    monkeypatch.setattr(pipeline_module, "_lock_holder", "retention")

    acquired, reason = pipeline_module._acquire_for_pipeline()

    assert acquired, f"run dropped while the lock was free: {reason}"
    fake.release()
    pipeline_module._lock_holder = None


def test_a_disabled_schedule_cannot_collide_with_retention(client):
    """No pipeline job exists when the schedule is off, so there is nothing to
    reject — and rejecting would strand retention at whatever it was."""
    assert client.put("/api/settings/schedule", json={"enabled": False}).status_code == 200

    res = client.put("/api/settings/schedule", json={"retention_at_time": "01:00"})

    assert res.status_code == 200, res.json()
    assert res.json()["retention_at_time"] == "01:00"


def test_enabling_onto_retention_is_still_rejected(client):
    """Turning the schedule back on at retention's time is a real collision."""
    client.put("/api/settings/schedule", json={"enabled": False})
    res = client.put(
        "/api/settings/schedule",
        json={"enabled": True, "mode": "daily", "at_time": "00:00", "retention_at_time": "00:00"},
    )
    assert res.status_code == 400


def test_modes_match_the_enum():
    """settings.PIPELINE_MODES mirrors PipelineMode because settings.py cannot
    import the database package — shared.py imports settings first. Pin them."""
    from src.database.models.enums import PipelineMode

    assert settings.PIPELINE_MODES == tuple(m.value for m in PipelineMode)


def test_a_dropped_run_is_recorded_so_the_dashboard_can_show_it(monkeypatch, engine):
    """The fire is consumed, so nothing retries it. Without a row the loss is
    invisible outside container logs."""
    from src.database.models.enums import RunStatus
    from src.database.repositories import WorkflowRunRepository

    monkeypatch.setattr(pipeline_module, "engine", engine)
    monkeypatch.setattr(pipeline_module, "RETENTION_WAIT_SECONDS", 0.3)
    assert pipeline_module.try_acquire_lock_for_retention()
    try:
        pipeline_module.run_pipeline("schedule")
    finally:
        pipeline_module.release_run_lock()

    with Session(engine) as session:
        runs = WorkflowRunRepository(session).get_recent(5)
        latest = runs[0]
        assert latest.status == RunStatus.FAILED.value
        assert "retention still running" in (latest.error or "")


def test_a_second_run_is_not_recorded_as_a_dropped_run(monkeypatch, engine):
    """max_instances=1 doing its job is not a failure worth a row."""
    from src.database.repositories import WorkflowRunRepository

    monkeypatch.setattr(pipeline_module, "engine", engine)
    assert pipeline_module._acquire_for_pipeline()[0]
    try:
        pipeline_module.run_pipeline("schedule")
    finally:
        pipeline_module.release_run_lock()

    with Session(engine) as session:
        assert WorkflowRunRepository(session).get_recent(5) == []
