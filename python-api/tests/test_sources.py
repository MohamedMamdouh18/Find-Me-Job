"""Per-source toggles: what the endpoints do, and what the pipeline does with them.

The interesting case is not "a disabled source does not run" but what happens when
every source is off — scoring reads the queue from the database, not from the
scrapers, so that run must still drain a backlog rather than exit early.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool

import src.database.models  # noqa: F401
from src.database.core import get_session
from src.database.models import FilteredJob, JobSource, PendingJob, RunEvent
from src.database.repositories import SourceRepository
from src.main import app
from src.schemas.jobs import PendingJobRequest
from src.services import pipeline as pipeline_module
from src.services import settings as settings_module


def _engine():
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
def client():
    engine = _engine()

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    test_client = TestClient(app)
    test_client.engine = engine  # type: ignore[attr-defined]
    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def harness(monkeypatch):
    engine = _engine()
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
    monkeypatch.setattr(pipeline_module, "score_job", lambda ctx, job, cv: (80, "letter"))
    return engine


def test_every_registered_source_is_listed_and_enabled_by_default(client):
    """Asserts the property, not the census: a phase that adds a feed should not have to
    edit this test, but a source that arrives switched off or unlabelled should fail it."""
    from src.scrapers import SOURCES, SOURCE_LABELS

    body = client.get("/api/sources").json()

    assert {row["name"] for row in body} == set(SOURCES)
    assert all(row["enabled"] for row in body)
    assert all(row["label"] == SOURCE_LABELS[row["name"]] for row in body)


def test_toggling_a_source_persists(client):
    res = client.put("/api/sources/linkedin", json={"enabled": False})
    assert res.status_code == 200

    listed = {row["name"]: row["enabled"] for row in client.get("/api/sources").json()}
    assert listed["linkedin"] is False
    assert all(enabled for name, enabled in listed.items() if name != "linkedin")

    with Session(client.engine) as session:
        assert session.get(JobSource, "linkedin").enabled is False


def test_an_unknown_source_is_a_404(client):
    assert client.put("/api/sources/monster", json={"enabled": False}).status_code == 404


def test_a_disabled_source_does_not_run(harness, monkeypatch):
    engine = harness
    scraped: list[str] = []

    def linkedin(ctx, kw):
        scraped.append("linkedin")
        return [_job("a")]

    def remoteok(ctx, kw):
        scraped.append("remoteok")
        return [_job("b")]

    monkeypatch.setattr(pipeline_module, "SOURCES", {"linkedin": linkedin, "remoteok": remoteok})
    # remoteok is a filtered source, so give the run keywords its jobs can match —
    # otherwise the gate drops them and the assertion below reads as a disabled source.
    monkeypatch.setattr(
        pipeline_module,
        "extract_or_get_keywords",
        lambda ctx: ("cv text", {"titles": ["Engineer"], "skills": ["python", "engineer"]}),
    )
    with Session(engine) as session:
        repo = SourceRepository(session)
        repo.reconcile({"linkedin": "LinkedIn", "remoteok": "RemoteOK"})
        repo.set_enabled("linkedin", False)
        session.commit()

    pipeline_module.run_pipeline("manual")

    assert scraped == ["remoteok"]
    with Session(engine) as session:
        assert {job.id for job in session.exec(select(FilteredJob)).all()} == {"b"}


def test_a_source_with_no_row_still_runs(harness, monkeypatch):
    """An upgrade must not stop scraping while the table is empty."""
    engine = harness
    monkeypatch.setattr(pipeline_module, "SOURCES", {"linkedin": lambda ctx, kw: [_job("a")]})

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        assert len(session.exec(select(FilteredJob)).all()) == 1


def test_every_source_disabled_still_drains_the_queue(harness, monkeypatch):
    engine = harness
    monkeypatch.setattr(
        pipeline_module,
        "SOURCES",
        {"linkedin": lambda ctx, kw: [_job("never")], "remoteok": lambda ctx, kw: [_job("nope")]},
    )
    with Session(engine) as session:
        repo = SourceRepository(session)
        repo.reconcile({"linkedin": "LinkedIn", "remoteok": "RemoteOK"})
        repo.set_enabled("linkedin", False)
        repo.set_enabled("remoteok", False)
        session.add(PendingJob(**_job("backlog").model_dump()))
        session.commit()

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        assert session.exec(select(PendingJob)).all() == [], "queue was not drained"
        assert {job.id for job in session.exec(select(FilteredJob)).all()} == {"backlog"}


def test_a_resume_says_nothing_about_disabled_sources(harness, monkeypatch):
    """A resume does not scrape at all, so it has no opinion on which sources are
    off: emitting scrape.disabled there would put a misleading row in run history."""
    engine = harness
    monkeypatch.setattr(pipeline_module, "SOURCES", {"linkedin": lambda ctx, kw: [_job("a")]})
    with Session(engine) as session:
        repo = SourceRepository(session)
        repo.reconcile({"linkedin": "LinkedIn"})
        repo.set_enabled("linkedin", False)
        session.add(PendingJob(**_job("backlog").model_dump()))
        session.commit()

    pipeline_module.run_pipeline("resume")

    with Session(engine) as session:
        stages = [e.stage for e in session.exec(select(RunEvent)).all()]
    assert "scrape.skipped" in stages
    assert "scrape.disabled" not in stages
