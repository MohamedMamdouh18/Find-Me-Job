# Regressions found by /qa on 2026-09-17
# Report: .gstack/qa-reports/qa-report-localhost-2026-09-17.md

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool

import src.database.models  # noqa: F401
from src.database.core import get_session
from src.database.models import FilteredJob, JobStatusHistory
from src.database.models.blocked_company import BlockedCompany
from src.database.models.enums import AiStatus, UserStatus
from src.database.models.starred_company import StarredCompany
from src.database.repositories import BlockedCompanyRepository
from src.database.repositories.filtered_jobs import FilteredJobRepository
from src.database.repositories.starred_companies import StarredCompanyRepository
from src.main import app
from src.services import settings


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    return engine


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


def _job(job_id="job_1", status=UserStatus.NEW) -> FilteredJob:
    return FilteredJob(
        id=job_id, title="Engineer", company="Acme", location="Remote",
        applylink="https://acme.test/1", description="d", website="LinkedIn",
        score=80, ai_status=AiStatus.FIT, user_status=status,
    )


# Regression: ISSUE-001 — "١٢:٠٠" parsed as 12:00 and was stored with Arabic digits
@pytest.mark.parametrize("raw", ["١٢:٠٠", "12", "12:", "123:00", "25:00", "12:60", "", "ab:cd"])
def test_clock_rejects_non_ascii_and_malformed_times(raw):
    with pytest.raises(ValueError):
        settings.parse_setting("PIPELINE_AT_TIME", raw)


@pytest.mark.parametrize("raw,hour,minute", [("01:00", 1, 0), ("1:05", 1, 5), ("12:5", 12, 5), (" 23:59 ", 23, 59)])
def test_clock_accepts_hh_mm(raw, hour, minute):
    parsed = settings.parse_setting("RETENTION_AT_TIME", raw)
    assert (parsed.hour, parsed.minute) == (hour, minute)


def test_schedule_endpoint_refuses_non_ascii_digits(client):
    res = client.put("/api/settings/schedule", json={"at_time": "١٢:٠٠"})
    assert res.status_code == 400


# Regression: ISSUE-002 — toggling "Acme, Inc." with "acme" blocked added a second row,
# then toggling again said unblocked while "acme" kept blocking the company
def test_toggle_unblocks_every_spelling_is_blocked_matches(engine):
    with Session(engine) as session:
        repo = BlockedCompanyRepository(session)
        repo.add("acme")
        session.commit()

        is_blocked, _ = repo.toggle("Acme, Inc.")
        session.commit()

        assert is_blocked is False
        assert repo.is_blocked("Acme, Inc.") is False
        assert session.exec(select(BlockedCompany)).all() == []


# Regression: ISSUE-003 — two tabs adding the same company raced past the existence check
# and the loser's commit hit UNIQUE(company_name) as a 500
def test_add_blocked_race_returns_409(client, engine, monkeypatch):
    with Session(engine) as session:
        session.add(BlockedCompany(company_name="acme"))
        session.commit()
    monkeypatch.setattr(BlockedCompanyRepository, "is_blocked", lambda self, name: False)

    assert client.post("/api/blocked", json={"company_name": "Acme"}).status_code == 409


def test_add_starred_race_returns_409(client, engine, monkeypatch):
    with Session(engine) as session:
        session.add(StarredCompany(company_name="acme"))
        session.commit()
    monkeypatch.setattr(StarredCompanyRepository, "is_starred", lambda self, name: False)

    assert client.post("/api/starred", json={"company_name": "Acme"}).status_code == 409


def test_toggle_blocked_insert_race_reports_blocked(client, engine, monkeypatch):
    with Session(engine) as session:
        session.add(BlockedCompany(company_name="acme"))
        session.commit()
    monkeypatch.setattr(BlockedCompanyRepository, "get_all", lambda self, search=None: [])

    res = client.post("/api/blocked/toggle", json={"company_name": "acme"})
    assert res.status_code == 200
    assert res.json() == {"is_blocked": True}


def test_toggle_starred_insert_race_reports_starred(client, engine, monkeypatch):
    with Session(engine) as session:
        session.add(StarredCompany(company_name="acme"))
        session.commit()
    monkeypatch.setattr(StarredCompanyRepository, "find_by_name", lambda self, name: None)

    res = client.post("/api/starred/toggle", json={"company_name": "acme"})
    assert res.status_code == 200
    assert res.json() == {"is_starred": True}


# Regression: ISSUE-004 — two sessions setting the same status both read the old value
# and each wrote a job_status_history row
def test_concurrent_same_status_writes_one_history_row(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as seed:
        seed.add(_job())
        seed.commit()

    with Session(engine) as tab_a, Session(engine) as tab_b:
        # Tab B has already loaded the job as "new". Keep the reference: the identity map
        # is weak, and a dropped object would be re-read fresh, hiding the race.
        stale = tab_b.get(FilteredJob, "job_1")  # noqa: F841
        assert FilteredJobRepository(tab_a).update_status("job_1", UserStatus.APPLIED)
        tab_a.commit()
        assert FilteredJobRepository(tab_b).update_status("job_1", UserStatus.APPLIED)
        tab_b.commit()

    with Session(engine) as check:
        rows = check.exec(select(JobStatusHistory).where(JobStatusHistory.job_id == "job_1")).all()
        assert [r.status for r in rows] == ["applied"]
        assert check.get(FilteredJob, "job_1").user_status == UserStatus.APPLIED


def test_status_change_still_writes_history(engine):
    with Session(engine) as session:
        session.add(_job())
        session.commit()
        repo = FilteredJobRepository(session)
        repo.update_status("job_1", UserStatus.INTERVIEW)
        repo.update_status("job_1", UserStatus.INTERVIEW)
        session.commit()
        rows = session.exec(select(JobStatusHistory)).all()
        assert [r.status for r in rows] == ["interview"]


# Regression: ISSUE-005 — careers_url accepted javascript: and file: and rendered them as links
@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///etc/passwd", "ftp://acme.test", "acme.test/careers"]
)
def test_starred_rejects_non_http_careers_url(client, url):
    res = client.post("/api/starred", json={"company_name": "acme", "careers_url": url})
    assert res.status_code == 422


def test_starred_accepts_http_url_and_blank(client, engine):
    assert client.post(
        "/api/starred", json={"company_name": "acme", "careers_url": "https://acme.test/jobs"}
    ).status_code == 201
    assert client.post("/api/starred", json={"company_name": "globex", "careers_url": ""}).status_code == 201


def test_starred_patch_rejects_javascript_url(client, engine):
    with Session(engine) as session:
        entry = StarredCompany(company_name="acme")
        session.add(entry)
        session.commit()
        entry_id = entry.id
    res = client.patch(f"/api/starred/{entry_id}", json={"careers_url": "javascript:alert(1)"})
    assert res.status_code == 422


# Regression: ISSUE-006 — a blank company name was stored as an empty row
@pytest.mark.parametrize("path", ["/api/blocked", "/api/blocked/toggle", "/api/starred", "/api/starred/toggle"])
@pytest.mark.parametrize("name", ["", "   "])
def test_blank_company_name_is_rejected(client, engine, path, name):
    assert client.post(path, json={"company_name": name}).status_code == 422
    with Session(engine) as session:
        assert session.exec(select(BlockedCompany)).all() == []
        assert session.exec(select(StarredCompany)).all() == []


# Regression: ISSUE-007 — PATCH status on a job that does not exist answered 200 ok
def test_status_update_on_missing_job_is_404(client):
    res = client.patch("/api/jobs/filtered/nope/status", json={"user_status": "applied"})
    assert res.status_code == 404
