"""End-to-end run_pipeline tests with stubbed scrapers and LLM.

Covers the two failure modes the pipeline had no coverage for:
  - the pending queue was never drained, so every run re-scored the whole backlog
  - one job raising aborted the run, leaving every job behind it unscored
"""

import pytest
from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool

import src.database.models  # noqa: F401
from src.database.models import PendingJob, FilteredJob, WorkflowRun
from src.database.models.enums import AiStatus
from src.schemas.jobs import PendingJobRequest
from src.services import pipeline as pipeline_module
from src.services.run_context import get_current_progress
from src.services import settings as settings_module


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
    """Wires run_pipeline to an in-memory DB with stubbed scrapers, LLM and notifications."""
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
    monkeypatch.setattr(pipeline_module, "notify", lambda *a, **k: None)
    return engine


def test_pipeline_drains_pending_queue(harness, monkeypatch):
    """Finding 1: a scored job must not stay in pending_jobs and be re-scored next run."""
    engine = harness
    monkeypatch.setattr(
        pipeline_module, "SOURCES", {"stub": lambda ctx, kw: [_job("a"), _job("b")]}
    )
    monkeypatch.setattr(pipeline_module, "score_job", lambda ctx, job, cv: (80, "letter"))

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        assert session.exec(select(PendingJob)).all() == [], "pending_jobs was not drained"
        assert len(session.exec(select(FilteredJob)).all()) == 2

    # A second run with no new jobs must score nothing, not re-score the backlog.
    scored: list[str] = []

    def counting_score(ctx, job, cv):
        scored.append(job.id)
        return 80, "letter"

    monkeypatch.setattr(pipeline_module, "score_job", counting_score)
    pipeline_module.run_pipeline("manual")
    assert scored == [], "second run re-scored jobs that were already filtered"


def test_pipeline_jobs_scraped_counts_new_jobs_only(harness, monkeypatch):
    """Finding 1 knock-on: jobs_scraped labelled total queue depth as 'scraped this run'."""
    engine = harness
    monkeypatch.setattr(pipeline_module, "SOURCES", {"stub": lambda ctx, kw: [_job("a")]})
    monkeypatch.setattr(pipeline_module, "score_job", lambda ctx, job, cv: (80, "letter"))

    pipeline_module.run_pipeline("manual")

    # Leave a stale row in the queue that this run did not scrape.
    with Session(engine) as session:
        session.add(PendingJob(**_job("leftover").model_dump()))
        session.commit()

    monkeypatch.setattr(pipeline_module, "SOURCES", {"stub": lambda ctx, kw: [_job("c")]})
    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        runs = session.exec(select(WorkflowRun).order_by(WorkflowRun.id)).all()
        assert runs[1].jobs_scraped == 1, (
            f"jobs_scraped={runs[1].jobs_scraped}, expected 1 newly queued job "
            "(queue depth was 2 because of the leftover row)"
        )


def test_pipeline_isolates_a_failing_job(harness, monkeypatch):
    """Finding 7: one job raising must not abort the run or strand the jobs behind it."""
    engine = harness
    monkeypatch.setattr(
        pipeline_module,
        "SOURCES",
        {"stub": lambda ctx, kw: [_job("good1"), _job("poison"), _job("good2")]},
    )

    def flaky_score(ctx, job, cv):
        if job.id == "poison":
            raise ValueError("could not parse LLM response")
        return 80, "letter"

    monkeypatch.setattr(pipeline_module, "score_job", flaky_score)

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        filtered = {j.id for j in session.exec(select(FilteredJob)).all()}
        assert filtered == {"good1", "good2"}, "jobs behind the failing one were not scored"

        run = session.exec(select(WorkflowRun)).one()
        assert run.status == "success", "one bad job failed the whole run"

        # The poison job must not survive to block the next run at the same index.
        assert session.exec(select(PendingJob)).all() == [], "failing job stayed in the queue"


def test_pipeline_failure_error_is_redacted(harness, monkeypatch):
    """Finding 9: workflow_runs.error must not store an unredacted provider response."""
    engine = harness
    monkeypatch.setattr(pipeline_module, "SOURCES", {})
    monkeypatch.setattr(pipeline_module, "score_job", lambda ctx, job, cv: (80, "letter"))

    def exploding_keywords(ctx):
        raise RuntimeError('LLM API returned HTTP 401: {"api_key": "sk-secret-value"}')

    monkeypatch.setattr(pipeline_module, "extract_or_get_keywords", exploding_keywords)

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        run = session.exec(select(WorkflowRun)).one()
        assert run.status == "failed"
        assert "sk-secret-value" not in (run.error or ""), (
            "raw secret stored in workflow_runs.error"
        )
        assert "[REDACTED]" in (run.error or "")


def test_pipeline_marks_below_threshold_not_fit(harness, monkeypatch):
    """The fit/not-fit split is decided once, in run_pipeline, against FILTERING_SCORE."""
    engine = harness
    monkeypatch.setattr(
        pipeline_module, "SOURCES", {"stub": lambda ctx, kw: [_job("low"), _job("high")]}
    )
    monkeypatch.setattr(
        pipeline_module,
        "score_job",
        lambda ctx, job, cv: ((30, "") if job.id == "low" else (90, "letter")),
    )

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        by_id = {j.id: j for j in session.exec(select(FilteredJob)).all()}
        assert by_id["low"].ai_status == AiStatus.NOT_FIT
        assert by_id["high"].ai_status == AiStatus.FIT


def test_progress_is_cleared_when_a_run_ends(harness, monkeypatch):
    """Progress is a process global. A stale value makes GET /api/runs/current
    report a finished run as live forever, which hides the dashboard run controls."""
    monkeypatch.setattr(pipeline_module, "SOURCES", {"stub": lambda ctx, kw: [_job("a")]})
    monkeypatch.setattr(pipeline_module, "score_job", lambda ctx, job, cv: (80, "letter"))

    pipeline_module.run_pipeline("manual")

    assert get_current_progress() is None, "finished run left behind in Progress"
