"""The company list as a source: detection verdicts, the switch, and scraping on demand.

The rule this file exists to enforce is that nothing lies about what it can do. A careers
page we cannot read says so, its switch refuses to turn on, and a company that returns
nothing twice running takes itself out of the workflow rather than contributing a silent
zero to every run from then on.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool

import src.database.models  # noqa: F401
from src.database.core import get_session
from src.database.models import PendingJob, SeenJob
from src.database.models.starred_company import StarredCompany
from src.database.repositories.companies import CompanyRepository
from src.main import app
from src.schemas.jobs import PendingJobRequest
from src.scrapers import companies as companies_module

GREENHOUSE_PAGE = """
<html><body>
  <a href="https://boards.greenhouse.io/acme">See our openings</a>
</body></html>
"""

JSONLD_PAGE = """
<html><head>
<script type="application/ld+json">
{"@type": "JobPosting", "title": "Platform Engineer",
 "description": "&lt;p&gt;We need a platform engineer.&lt;/p&gt;",
 "url": "https://acme.test/jobs/1",
 "jobLocation": {"address": {"addressLocality": "Berlin", "addressCountry": "DE"}}}
</script>
</head><body>Careers</body></html>
"""

SPA_PAGE = "<html><head><style>body{}</style></head><body><div id='root'></div></body></html>"


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


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


def _company(engine, **fields) -> int:
    defaults = {"company_name": "acme", "careers_url": "https://acme.test/careers"}
    with Session(engine) as session:
        company = StarredCompany(**{**defaults, **fields})
        session.add(company)
        session.commit()
        session.refresh(company)
        return company.id


def _a_job() -> PendingJobRequest:
    return PendingJobRequest(
        id="greenhouse_acme_1",
        title="Engineer",
        company="Acme",
        location="Remote",
        applylink="https://acme.test/1",
        description="python",
        website="Greenhouse",
    )


# ── detection ────────────────────────────────────────────────────────────────


def test_a_board_url_is_recognised_without_fetching_anything():
    assert companies_module.detect_from_url("https://jobs.lever.co/palantir") == (
        "lever",
        "palantir",
    )
    assert companies_module.detect_from_url("https://boards.greenhouse.io/stripe") == (
        "greenhouse",
        "stripe",
    )
    assert companies_module.detect_from_url("https://acme.test/careers") == (None, None)


def test_a_board_behind_a_company_domain_is_found_by_sniffing_the_page():
    """The case that matters: careers.acme.com is very often a board wearing a company
    domain, and matching on the URL alone would send it down the page path for nothing."""
    assert companies_module.detect_from_html(GREENHOUSE_PAGE, "https://acme.test/careers") == (
        "greenhouse",
        "acme",
    )


def test_structured_job_data_is_parsed_from_the_page():
    jobs = companies_module.jsonld_jobs(JSONLD_PAGE, "Acme", "https://acme.test/careers")

    assert len(jobs) == 1
    assert jobs[0].title == "Platform Engineer"
    assert jobs[0].company == "Acme"
    assert jobs[0].location == "Berlin, DE"
    assert "<p>" not in jobs[0].description and "&lt;" not in jobs[0].description


def test_a_page_with_nothing_readable_yields_no_jobs():
    assert companies_module.jsonld_jobs(SPA_PAGE, "Acme", "https://acme.test/careers") == []


def test_robots_disallowing_the_page_makes_it_unreadable(monkeypatch):
    """Google's careers page disallows its own paginated results; a page we are asked not
    to walk is 'cannot read', not a puzzle to solve."""
    monkeypatch.setattr(companies_module, "robots_allows", lambda url, interrupt=None: False)

    verdict = companies_module.detect("https://acme.test/careers")

    assert verdict["fetch_method"] == "unreadable"
    assert "robots" in verdict["fetch_note"].lower()


def test_a_page_that_cannot_be_read_says_why(monkeypatch):
    monkeypatch.setattr(companies_module, "robots_allows", lambda url, interrupt=None: True)
    monkeypatch.setattr(
        companies_module, "get", lambda url, **kw: type("R", (), {"text": SPA_PAGE})()
    )

    verdict = companies_module.detect("https://acme.test/careers")

    assert verdict["fetch_method"] == "unreadable"
    assert verdict["fetch_note"]


# ── the switch ───────────────────────────────────────────────────────────────


def test_the_switch_refuses_a_company_we_cannot_read(client):
    company_id = _company(client.engine, fetch_method="unreadable", fetch_note="SPA")

    res = client.patch(f"/api/companies/{company_id}", json={"in_workflow": True})

    assert res.status_code == 409
    with Session(client.engine) as session:
        assert session.get(StarredCompany, company_id).in_workflow is False


def test_the_switch_refuses_a_company_that_has_not_been_checked_yet(client):
    company_id = _company(client.engine, fetch_method="unknown")

    res = client.patch(f"/api/companies/{company_id}", json={"in_workflow": True})
    assert res.status_code == 409


def test_the_switch_works_once_a_board_is_detected(client):
    company_id = _company(client.engine, fetch_method="ats", ats="greenhouse", ats_token="acme")

    res = client.patch(f"/api/companies/{company_id}", json={"in_workflow": True})

    assert res.status_code == 200
    assert res.json()["in_workflow"] is True


def test_starring_and_scraping_are_separate_facts(client):
    """A competitor's board can be watched without its jobs being boosted in Phase 3."""
    company_id = _company(client.engine, fetch_method="ats", ats="greenhouse", ats_token="acme")

    client.patch(f"/api/companies/{company_id}", json={"starred": False, "in_workflow": True})

    row = client.get("/api/companies").json()[0]
    assert row["starred"] is False
    assert row["in_workflow"] is True


def test_a_new_careers_url_resets_the_verdict_and_schedules_a_check(client, monkeypatch):
    """The verdict belongs to the URL, so a new URL is unchecked until proven otherwise.

    The detection itself is stubbed here: it runs in the background against its own
    session on the real engine — which is what keeps a slow careers page out of this
    request — so it is deliberately not reachable from the test's in-memory database.
    What this asserts is the part the endpoint owns: the reset, and that a check was
    scheduled at all.
    """
    scheduled: list[int] = []
    monkeypatch.setattr(
        "src.routes.companies_route._detect_in_background", scheduled.append
    )
    company_id = _company(client.engine, fetch_method="ats", ats="greenhouse", ats_token="acme")

    res = client.patch(
        f"/api/companies/{company_id}", json={"careers_url": "https://acme.test/jobs"}
    )

    assert res.json()["fetch_method"] == "unknown"
    assert res.json()["ats"] is None
    assert scheduled == [company_id]


# ── scraping on demand ───────────────────────────────────────────────────────


def test_scrape_now_queues_and_reports_counts(client, monkeypatch):
    company_id = _company(client.engine, fetch_method="ats", ats="greenhouse", ats_token="acme")
    monkeypatch.setattr(
        "src.routes.companies_route.fetch_company",
        lambda company, interrupt=None: [_a_job()],
    )

    res = client.post(f"/api/companies/{company_id}/scrape")

    assert res.status_code == 200
    assert res.json()["queued"] == 1
    with Session(client.engine) as session:
        assert len(session.exec(select(PendingJob)).all()) == 1


def test_scrape_now_opens_no_run_row(client, monkeypatch):
    """It is not a run: the pipeline stays the only writer of workflow_runs."""
    from src.database.models import WorkflowRun

    company_id = _company(client.engine, fetch_method="ats", ats="greenhouse", ats_token="acme")
    monkeypatch.setattr(
        "src.routes.companies_route.fetch_company", lambda company, interrupt=None: []
    )

    client.post(f"/api/companies/{company_id}/scrape")

    with Session(client.engine) as session:
        assert session.exec(select(WorkflowRun)).all() == []


def test_scrape_now_works_with_the_switch_off(client, monkeypatch):
    """Trying a careers URL before committing it to every run is the point of it."""
    company_id = _company(
        client.engine, fetch_method="ats", ats="greenhouse", ats_token="acme", in_workflow=False
    )
    monkeypatch.setattr(
        "src.routes.companies_route.fetch_company", lambda company, interrupt=None: []
    )

    assert client.post(f"/api/companies/{company_id}/scrape").status_code == 200


def test_a_blocked_company_is_blocked_even_when_it_is_in_the_list(client, monkeypatch):
    from src.database.models import BlockedCompany

    company_id = _company(client.engine, fetch_method="ats", ats="greenhouse", ats_token="acme")
    with Session(client.engine) as session:
        session.add(BlockedCompany(company_name="acme"))
        session.commit()

    monkeypatch.setattr(
        "src.routes.companies_route.fetch_company",
        lambda company, interrupt=None: [_a_job()],
    )

    res = client.post(f"/api/companies/{company_id}/scrape")

    assert res.json()["blocked"] == 1
    with Session(client.engine) as session:
        assert session.exec(select(PendingJob)).all() == []
        assert len(session.exec(select(SeenJob)).all()) == 1


# ── health ───────────────────────────────────────────────────────────────────


def test_two_empty_fetches_take_a_company_out_of_the_workflow(client):
    company_id = _company(
        client.engine, fetch_method="ats", ats="greenhouse", ats_token="dead", in_workflow=True
    )

    with Session(client.engine) as session:
        repo = CompanyRepository(session)
        company = repo.get(company_id)
        repo.record_fetch(company, 0)
        assert company.in_workflow is True, "one empty fetch is bad luck, not a verdict"
        repo.record_fetch(company, 0)
        session.commit()

    with Session(client.engine) as session:
        company = session.get(StarredCompany, company_id)
    assert company.in_workflow is False
    assert company.fetch_method == "unreadable"
    assert company.fetch_note


def test_a_successful_fetch_clears_the_empty_streak(client):
    company_id = _company(client.engine, fetch_method="ats", ats="greenhouse", ats_token="acme")

    with Session(client.engine) as session:
        repo = CompanyRepository(session)
        company = repo.get(company_id)
        repo.record_fetch(company, 0)
        repo.record_fetch(company, 7)
        repo.record_fetch(company, 0)
        session.commit()

    with Session(client.engine) as session:
        company = session.get(StarredCompany, company_id)
    assert company.last_job_count == 0
    assert company.consecutive_empty == 1
    assert company.fetch_method == "ats"


def test_a_failed_fetch_is_not_counted_as_an_empty_one(client, monkeypatch):
    """Two flaky nights must not turn a healthy company unreadable with a note claiming
    it returned no jobs. A failure is a failure; only a successful empty fetch counts."""
    from src.services import pipeline as pipeline_module
    from src.services.run_context import RunContext
    from src.database.repositories import WorkflowRunRepository

    company_id = _company(
        client.engine, fetch_method="ats", ats="greenhouse", ats_token="acme", in_workflow=True
    )

    def always_fails(company, interrupt=None):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(companies_module, "fetch_company", always_fails)

    with Session(client.engine) as session:
        run = WorkflowRunRepository(session).start(trigger="manual")
        session.commit()
        ctx = RunContext(run.id, session)
        for _ in range(3):
            companies_module.fetch(ctx, {})
        session.commit()

    with Session(client.engine) as session:
        company = session.get(StarredCompany, company_id)
    assert company.in_workflow is True, "three failures should not disable the company"
    assert company.fetch_method == "ats"
    assert company.consecutive_empty == 0


def test_pasting_a_careers_url_schedules_a_check(client, monkeypatch):
    """The verdict is the point of the feature, and this is the route the dashboard uses
    to write a URL — so it is the route that has to start the check."""
    scheduled: list[int] = []
    monkeypatch.setattr("src.routes.starred_route._detect_in_background", scheduled.append)

    res = client.post(
        "/api/starred", json={"company_name": "newco", "careers_url": "https://newco.test/jobs"}
    )

    assert res.status_code == 201
    assert scheduled == [res.json()["id"]]


def test_changing_a_careers_url_clears_the_old_board(client, monkeypatch):
    """Otherwise the company keeps its previous token and goes on reporting healthy jobs
    from the wrong employer."""
    monkeypatch.setattr("src.routes.starred_route._detect_in_background", lambda _id: None)
    company_id = _company(client.engine, fetch_method="ats", ats="greenhouse", ats_token="acme")

    client.patch(f"/api/starred/{company_id}", json={"careers_url": "https://acme.test/other"})

    with Session(client.engine) as session:
        company = session.get(StarredCompany, company_id)
    assert company.fetch_method == "unknown"
    assert company.ats_token is None


def test_a_company_that_made_no_request_is_not_counted_as_empty(client, monkeypatch):
    """A row whose page has not been checked, or cannot be read, returns nothing without
    fetching anything. Counting that as an empty board would mark it "returned no jobs
    twice in a row" for something it never did."""
    company_id = _company(client.engine, fetch_method="unknown")

    for _ in range(3):
        client.post(f"/api/companies/{company_id}/scrape")

    with Session(client.engine) as session:
        company = session.get(StarredCompany, company_id)
    assert company.fetch_method == "unknown"
    assert company.consecutive_empty == 0
    assert company.fetch_note is None
