from datetime import datetime, timedelta
from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool

import src.database.models  # noqa: F401
from src.database.models import WorkflowRun, RunEvent
from src.database.repositories import WorkflowRunRepository
from src.services.run_context import (
    RunContext,
    redact_secrets,
    get_current_progress,
    set_current_progress,
)


def test_emit_writes_event_and_updates_run():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        run_repo = WorkflowRunRepository(session)
        run = run_repo.start(trigger="manual")
        session.commit()

        ctx = RunContext(run.id, session)
        ctx.emit(
            stage="scrape.linkedin",
            message="Found 10 jobs",
            detail="Processing page 1",
            done=1,
            total=5,
            context="Header: Bearer sk-secret123456789",
        )

        # 1. Assert run_events row was written
        events = session.exec(select(RunEvent).where(RunEvent.run_id == run.id)).all()
        assert len(events) == 1
        assert events[0].stage == "scrape.linkedin"
        assert events[0].message == "Found 10 jobs"
        assert "Bearer [REDACTED]" in events[0].context
        assert "sk-secret123456789" not in events[0].context

        # 2. Assert workflow_runs stage and stage_detail updated
        updated_run = session.get(WorkflowRun, run.id)
        assert updated_run.stage == "scrape.linkedin"
        assert updated_run.stage_detail == "Processing page 1"

        # 3. Assert in-memory progress updated
        progress = get_current_progress()
        assert progress is not None
        assert progress.run_id == run.id
        assert progress.stage == "scrape.linkedin"
        assert progress.detail == "Processing page 1"
        assert progress.done == 1
        assert progress.total == 5


def test_wait_sets_waiting_until_without_db_write():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        run_repo = WorkflowRunRepository(session)
        run = run_repo.start(trigger="schedule")
        session.commit()

        ctx = RunContext(run.id, session)
        ctx.emit("score", "Scoring job 1")

        events_before = len(session.exec(select(RunEvent)).all())

        # Test wait for 0 seconds (or fast mock)
        import time

        orig_sleep = time.sleep
        slept = []
        time.sleep = lambda s: slept.append(s)
        try:
            ctx.wait(5)
        finally:
            time.sleep = orig_sleep

        assert slept == [5]
        events_after = len(session.exec(select(RunEvent)).all())
        assert events_after == events_before  # No DB writes during wait


def test_redact_secrets():
    raw = (
        'Authorization: Bearer my-secret-api-token-12345, '
        'bot123456789:ABCdefGHIjklMNOpqrSTUvwxYZ123456789, '
        '{"password": "supersecretpassword123"}'
    )
    redacted = redact_secrets(raw)
    assert "my-secret-api-token-12345" not in redacted
    assert "Bearer [REDACTED]" in redacted
    assert "123456789:ABCdefGHI" not in redacted
    assert "[REDACTED_TELEGRAM_TOKEN]" in redacted
    assert "supersecretpassword123" not in redacted
