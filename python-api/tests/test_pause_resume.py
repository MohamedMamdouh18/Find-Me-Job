"""Pause and resume of the scoring run.

Pause works because the scoring loop drains pending_jobs one atomic commit at a time,
so the untouched remainder of the queue IS the resume cursor. These tests pin that
property down: what is left queued after a pause, and that a resume finishes it.
"""

from datetime import timedelta

import pytest
from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool

import src.database.models  # noqa: F401
from src.database.models import PendingJob, FilteredJob, RunEvent, WorkflowRun
from src.database.models.enums import RunStatus
from src.database.repositories import WorkflowRunRepository
from src.schemas.jobs import PendingJobRequest
from src.services import pipeline as pipeline_module
from src.services.run_context import PauseRequested
from src.services import settings as settings_module
from src.shared import now


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _job(job_id: str) -> PendingJobRequest:
    return PendingJobRequest(
        id=job_id,
        title=f"Engineer {job_id}",
        company=f"Company {job_id}",
        location="Remote",
        applylink=f"https://example.test/{job_id}",
        description="We need a python engineer.",
        website="linkedin",
        easy_apply=False,
    )


@pytest.fixture
def harness(monkeypatch):
    engine = _make_engine()
    monkeypatch.setattr(pipeline_module, "engine", engine)
    monkeypatch.setattr(settings_module, "get_scoring_delay", lambda: 0)
    monkeypatch.setattr(settings_module, "get_filtering_score", lambda: 60)
    monkeypatch.setattr(settings_module, "get_auto_email", lambda: False)
    monkeypatch.setattr(
        pipeline_module,
        "extract_or_get_keywords",
        lambda ctx: ("cv text", {"titles": [], "skills": []}),
    )
    monkeypatch.setattr(pipeline_module, "send_telegram", lambda *a, **k: None)
    # A pause request must never leak between runs or between tests.
    pipeline_module._pause_event.clear()
    pipeline_module._stop_event.clear()
    yield engine
    pipeline_module._pause_event.clear()
    pipeline_module._stop_event.clear()


def test_pause_leaves_the_remainder_queued(harness, monkeypatch):
    """The whole point: paused work is still in pending_jobs, not lost."""
    engine = harness
    monkeypatch.setattr(
        pipeline_module,
        "SOURCES",
        {"stub": lambda ctx, kw: [_job("a"), _job("b"), _job("c")]},
    )

    scored: list[str] = []

    def score_then_pause(ctx, job, cv):
        scored.append(job.id)
        # Ask for a pause from inside the first job, the way the HTTP route would.
        pipeline_module.request_pause()
        return 80, "letter"

    monkeypatch.setattr(pipeline_module, "score_job", score_then_pause)

    pipeline_module.run_pipeline("manual")

    assert len(scored) == 1, f"kept scoring after a pause was requested: {scored}"

    with Session(engine) as session:
        assert len(session.exec(select(FilteredJob)).all()) == 1
        left = {j.id for j in session.exec(select(PendingJob)).all()}
        assert len(left) == 2, f"remainder was not left queued: {left}"

        run = session.exec(select(WorkflowRun)).one()
        assert run.status == RunStatus.PAUSED
        assert run.finished_at is not None, "a paused run must close its row"
        assert run.error is None


def test_resume_scores_the_remainder_without_scraping(harness, monkeypatch):
    """Resume continues where the pause stopped and must not re-scrape."""
    engine = harness

    with Session(engine) as session:
        for jid in ("left1", "left2"):
            session.add(PendingJob(**_job(jid).model_dump()))
        # A paused run is what makes resume legal.
        run = WorkflowRunRepository(session).start(trigger="manual")
        run.status = RunStatus.PAUSED.value
        run.finished_at = now()
        session.commit()

    def exploding_source(ctx, kw):
        raise AssertionError("resume must not scrape")

    monkeypatch.setattr(pipeline_module, "SOURCES", {"stub": exploding_source})
    monkeypatch.setattr(pipeline_module, "score_job", lambda ctx, job, cv: (70, "letter"))

    pipeline_module.run_pipeline("resume")

    with Session(engine) as session:
        assert {j.id for j in session.exec(select(FilteredJob)).all()} == {"left1", "left2"}
        assert session.exec(select(PendingJob)).all() == []

        runs = session.exec(select(WorkflowRun).order_by(WorkflowRun.id)).all()
        assert len(runs) == 2, "resume should open its own run row"
        assert runs[1].trigger == "resume"
        assert runs[1].status == RunStatus.SUCCESS
        # Nothing was scraped, so the resume run claims no scrapes.
        assert runs[1].jobs_scraped == 0


def test_scheduled_run_is_skipped_while_paused(harness, monkeypatch):
    """A deliberate pause outranks the 01:00 cron."""
    engine = harness

    with Session(engine) as session:
        run = WorkflowRunRepository(session).start(trigger="manual")
        run.status = RunStatus.PAUSED.value
        run.finished_at = now()
        session.commit()

    monkeypatch.setattr(
        pipeline_module,
        "SOURCES",
        {"stub": lambda ctx, kw: (_ for _ in ()).throw(AssertionError("cron ran anyway"))},
    )

    pipeline_module.run_pipeline("schedule")

    with Session(engine) as session:
        assert len(session.exec(select(WorkflowRun)).all()) == 1, (
            "cron opened a run while paused"
        )


def test_manual_trigger_overrides_a_pause(harness, monkeypatch):
    """Only the cron defers. The user asking for work now is not overridden."""
    engine = harness

    with Session(engine) as session:
        run = WorkflowRunRepository(session).start(trigger="manual")
        run.status = RunStatus.PAUSED.value
        run.finished_at = now()
        session.commit()

    monkeypatch.setattr(pipeline_module, "SOURCES", {"stub": lambda ctx, kw: [_job("fresh")]})
    monkeypatch.setattr(pipeline_module, "score_job", lambda ctx, job, cv: (90, "letter"))

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        runs = session.exec(select(WorkflowRun).order_by(WorkflowRun.id)).all()
        assert len(runs) == 2
        assert runs[1].status == RunStatus.SUCCESS


def test_paused_run_survives_both_stale_sweeps(harness):
    """A pause can last days. Neither sweep may touch it."""
    engine = harness

    with Session(engine) as session:
        repo = WorkflowRunRepository(session)
        run = repo.start(trigger="manual")
        run.status = RunStatus.PAUSED.value
        run.finished_at = now()
        # Older than STALE_RUN_HOURS, which is what _expire_stale_runs looks for.
        run.started_at = now() - timedelta(hours=48)
        session.commit()
        run_id = run.id

        # _fail_stale_runs, reached from start() and from the shutdown hook
        repo.fail_running("server shutdown")
        session.commit()
        assert session.get(WorkflowRun, run_id).status == RunStatus.PAUSED

        # _expire_stale_runs, reached from every get_recent()
        repo.get_recent(20)
        session.commit()
        assert session.get(WorkflowRun, run_id).status == RunStatus.PAUSED


def test_pause_request_does_not_leak_into_the_next_run(harness, monkeypatch):
    """A stale event would instantly pause the following run at job one."""
    engine = harness
    monkeypatch.setattr(
        pipeline_module, "SOURCES", {"stub": lambda ctx, kw: [_job("a"), _job("b")]}
    )

    def score_then_pause(ctx, job, cv):
        pipeline_module.request_pause()
        return 80, "letter"

    monkeypatch.setattr(pipeline_module, "score_job", score_then_pause)
    pipeline_module.run_pipeline("manual")
    assert not pipeline_module._pause_event.is_set(), "pause event outlived the run"

    # The leftover job must now score normally.
    monkeypatch.setattr(pipeline_module, "score_job", lambda ctx, job, cv: (80, "letter"))
    pipeline_module.run_pipeline("resume")

    with Session(engine) as session:
        assert session.exec(select(PendingJob)).all() == []
        assert len(session.exec(select(FilteredJob)).all()) == 2


def test_pause_is_honoured_when_the_queue_is_empty(harness, monkeypatch):
    """A pause is observed only inside the scoring loop, so a run whose loop body
    never executes used to close as success and let the next cron run start."""
    engine = harness

    def scrape_then_user_pauses(ctx, kw):
        pipeline_module.request_pause()
        return []

    monkeypatch.setattr(pipeline_module, "SOURCES", {"stub": scrape_then_user_pauses})

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        run = session.exec(select(WorkflowRun)).one()
        assert run.status == RunStatus.PAUSED, "pause was swallowed by an empty queue"


def test_pause_on_the_last_job_still_pauses(harness, monkeypatch):
    """The common case: the pause lands while the final job is being scored, so the
    loop ends on its own and the break is never reached."""
    engine = harness
    monkeypatch.setattr(pipeline_module, "SOURCES", {"stub": lambda ctx, kw: [_job("only")]})

    def score_then_pause(ctx, job, cv):
        pipeline_module.request_pause()
        return 80, "letter"

    monkeypatch.setattr(pipeline_module, "score_job", score_then_pause)

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        run = session.exec(select(WorkflowRun)).one()
        assert run.status == RunStatus.PAUSED, "pause on the last job was swallowed"
        # The queue drained, so a resume has nothing to do - but the workflow is
        # still paused, which is what stops the 01:00 cron.
        assert session.exec(select(PendingJob)).all() == []


def test_pause_during_an_llm_call_leaves_the_job_queued(harness, monkeypatch):
    """A pause raised from inside call_llm is a pause, not a scoring failure: the
    job was never written or drained, so it must still be queued for the resume."""
    engine = harness
    monkeypatch.setattr(
        pipeline_module, "SOURCES", {"stub": lambda ctx, kw: [_job("a"), _job("b")]}
    )

    def score_raises_pause(ctx, job, cv):
        # What call_llm does when the event is set between retry attempts.
        pipeline_module.request_pause()
        raise PauseRequested("pause requested before LLM attempt")

    monkeypatch.setattr(pipeline_module, "score_job", score_raises_pause)

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        run = session.exec(select(WorkflowRun)).one()
        assert run.status == RunStatus.PAUSED
        assert run.error is None, "a pause must not be recorded as a failed run"
        # Nothing scored, and the abandoned job is still waiting.
        assert session.exec(select(FilteredJob)).all() == []
        assert len(session.exec(select(PendingJob)).all()) == 2


def test_llm_aborts_between_attempts_when_paused(harness):
    """call_llm must not sit through all five retries after a pause lands."""
    import threading
    from src.services.llm import call_llm

    event = threading.Event()
    event.set()
    with pytest.raises(PauseRequested):
        call_llm([{"role": "user", "content": "hi"}], interrupt=event)


def test_stop_ends_the_run_as_stopped_and_blocks_resume(harness, monkeypatch):
    """Stop is terminal and deliberately not resumable."""
    engine = harness
    monkeypatch.setattr(
        pipeline_module, "SOURCES", {"stub": lambda ctx, kw: [_job("a"), _job("b")]}
    )

    def score_then_stop(ctx, job, cv):
        pipeline_module.request_stop()
        return 80, "letter"

    monkeypatch.setattr(pipeline_module, "score_job", score_then_stop)

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        run = session.exec(select(WorkflowRun)).one()
        assert run.status == RunStatus.STOPPED
        assert run.error is None, "a stop must not be recorded as a failure"
        assert len(session.exec(select(PendingJob)).all()) == 1

        # Resume refuses anything that is not paused.
        latest = WorkflowRunRepository(session).get_latest()
        assert latest.status != RunStatus.PAUSED


def test_stopped_run_does_not_hold_the_schedule(harness, monkeypatch):
    """Pause holds the whole workflow; stop only ends its own run."""
    engine = harness

    with Session(engine) as session:
        run = WorkflowRunRepository(session).start(trigger="manual")
        run.status = RunStatus.STOPPED.value
        run.finished_at = now()
        session.commit()

    monkeypatch.setattr(pipeline_module, "SOURCES", {"stub": lambda ctx, kw: [_job("n")]})
    monkeypatch.setattr(pipeline_module, "score_job", lambda ctx, job, cv: (70, "l"))

    pipeline_module.run_pipeline("schedule")

    with Session(engine) as session:
        runs = session.exec(select(WorkflowRun).order_by(WorkflowRun.id)).all()
        assert len(runs) == 2, "the cron must still run after a stop"
        assert runs[1].status == RunStatus.SUCCESS


def test_stop_request_does_not_leak_into_the_next_run(harness, monkeypatch):
    engine = harness
    monkeypatch.setattr(pipeline_module, "SOURCES", {"stub": lambda ctx, kw: [_job("a")]})
    monkeypatch.setattr(
        pipeline_module, "score_job",
        lambda ctx, job, cv: (pipeline_module.request_stop(), (80, "l"))[1],
    )
    pipeline_module.run_pipeline("manual")
    assert not pipeline_module.is_stop_requested(), "stop event outlived the run"
    assert not pipeline_module.is_pause_requested(), "pause event outlived the run"


def test_stop_during_keyword_extraction_is_not_a_failed_run(harness, monkeypatch):
    """Phase 1 runs outside the scoring loop, so an interrupt there used to escape
    as a RuntimeError and fail the whole run."""
    engine = harness

    def keywords_interrupted(ctx):
        pipeline_module.request_stop()
        raise PauseRequested("run interrupted before LLM attempt")

    monkeypatch.setattr(pipeline_module, "extract_or_get_keywords", keywords_interrupted)
    monkeypatch.setattr(
        pipeline_module, "SOURCES",
        {"stub": lambda ctx, kw: (_ for _ in ()).throw(AssertionError("scraped anyway"))},
    )

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        run = session.exec(select(WorkflowRun)).one()
        assert run.status == RunStatus.STOPPED
        assert run.error is None, "an interrupt must never be recorded as a failure"


def test_pause_between_scrapers_skips_the_rest(harness, monkeypatch):
    """Scraping can run for minutes; an interrupt must land between sources."""
    engine = harness
    seen = []

    def first(ctx, kw):
        seen.append("first")
        pipeline_module.request_pause()
        return []

    def second(ctx, kw):
        seen.append("second")
        return []

    monkeypatch.setattr(pipeline_module, "SOURCES", {"a": first, "b": second})

    pipeline_module.run_pipeline("manual")

    assert seen == ["first"], f"kept scraping after an interrupt: {seen}"
    with Session(engine) as session:
        assert session.exec(select(WorkflowRun)).one().status == RunStatus.PAUSED


def test_interrupted_scrape_keeps_what_it_already_collected(harness, monkeypatch):
    """fetch() only hands jobs over on return, so raising past it binned the lot -
    and resume does not re-scrape, so those postings were gone for good."""
    engine = harness

    def partial_then_interrupt(ctx, kw):
        # What linkedin.fetch does now: swallow its own interrupt and return partial.
        pipeline_module.request_pause()
        return [_job("kept1"), _job("kept2")]

    monkeypatch.setattr(pipeline_module, "SOURCES", {"linkedin": partial_then_interrupt})

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        queued = {j.id for j in session.exec(select(PendingJob)).all()}
        assert queued == {"kept1", "kept2"}, f"scraped work was discarded: {queued}"
        assert session.exec(select(WorkflowRun)).one().status == RunStatus.PAUSED


def test_stopped_run_is_not_described_as_paused(harness, monkeypatch):
    """A stopped run pointing the user at Resume sends them to a 409."""
    engine = harness
    sent: list[str] = []
    monkeypatch.setattr(pipeline_module, "send_telegram", lambda text: sent.append(text))
    monkeypatch.setattr(
        pipeline_module, "SOURCES", {"stub": lambda ctx, kw: [_job("a"), _job("b")]}
    )

    def score_then_stop(ctx, job, cv):
        pipeline_module.request_stop()
        return 80, "letter"

    monkeypatch.setattr(pipeline_module, "score_job", score_then_stop)

    pipeline_module.run_pipeline("manual")

    assert sent, "no summary was sent"
    summary = sent[0]
    assert "stopped" in summary, summary
    assert "paused" not in summary, f"a stopped run called itself paused: {summary}"
    assert "Resume from the dashboard" not in summary, (
        f"a stopped run offered a Resume that answers 409: {summary}"
    )

    with Session(engine) as session:
        events = [e.stage for e in session.exec(select(RunEvent)).all()]
        assert "run.stopped" in events, events
