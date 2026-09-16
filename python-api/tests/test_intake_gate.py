"""The intake gate: what a run is allowed to queue, and in what order it walks.

Volume is not a side effect of the new sources, it is them. One feed offers six figures
of jobs and a company board carries every role an employer has, including the ones this
user would never open — and each queued job costs a wait and an LLM call. So the gate is
the phase's real constraint, and these are its rules:

  feeds are filtered against the CV keywords, companies are not
  a per-source ceiling stops one feed eating the run
  a run budget stops the total being absurd
  companies are walked before feeds, which is what makes "first wins" keep the better copy
"""

import pytest
from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool

import src.database.models  # noqa: F401
from src.database.models import FilteredJob, PendingJob, RunEvent
from src.schemas.jobs import PendingJobRequest
from src.services import pipeline as pipeline_module
from src.services import settings as settings_module

KEYWORDS = {"titles": ["Python Developer"], "skills": ["python", "django", "postgres"]}


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _job(
    job_id: str,
    title: str = "Python Developer",
    description: str = "python django postgres",
) -> PendingJobRequest:
    return PendingJobRequest(
        id=job_id,
        title=title,
        company=f"Company {job_id}",
        location="Remote",
        applylink=f"https://example.test/{job_id}",
        description=description,
        website="test",
        easy_apply=False,
    )


@pytest.fixture
def harness(monkeypatch):
    engine = _engine()
    monkeypatch.setattr(pipeline_module, "engine", engine)
    monkeypatch.setattr(settings_module, "get_scoring_delay", lambda: 0)
    monkeypatch.setattr(settings_module, "get_filtering_score", lambda: 60)
    monkeypatch.setattr(settings_module, "get_auto_email", lambda: False)
    monkeypatch.setattr(
        pipeline_module, "extract_or_get_keywords", lambda ctx: ("cv text", KEYWORDS)
    )
    monkeypatch.setattr(pipeline_module, "notify", lambda *a, **k: None)
    monkeypatch.setattr(pipeline_module, "score_job", lambda ctx, job, cv: (80, "letter"))
    settings_module.set_cache({})
    yield engine
    settings_module.set_cache({})


def _queued_ids(engine) -> set[str]:
    with Session(engine) as session:
        return {job.id for job in session.exec(select(FilteredJob)).all()} | {
            job.id for job in session.exec(select(PendingJob)).all()
        }


def _stages(engine) -> list[str]:
    with Session(engine) as session:
        return [event.stage for event in session.exec(select(RunEvent)).all()]


def test_a_feed_has_its_irrelevant_jobs_dropped(harness, monkeypatch):
    engine = harness
    monkeypatch.setattr(
        pipeline_module,
        "SOURCES",
        {
            "himalayas": lambda ctx, kw: [
                _job("relevant"),
                _job(
                    "irrelevant",
                    title="Warehouse Picker",
                    description="lifting, pallets, forklift",
                ),
            ]
        },
    )

    pipeline_module.run_pipeline("manual")

    assert _queued_ids(engine) == {"relevant"}


def test_a_company_keeps_jobs_the_filter_would_have_dropped(harness, monkeypatch):
    """The user named this company, so relevance is already established: a sideways role
    their CV keywords miss is exactly the job they want to see."""
    engine = harness
    monkeypatch.setattr(
        pipeline_module,
        "SOURCES",
        {
            "companies": lambda ctx, kw: [
                _job("sideways", title="Engineering Manager", description="leading teams"),
            ]
        },
    )

    pipeline_module.run_pipeline("manual")

    assert _queued_ids(engine) == {"sideways"}


def test_one_source_cannot_eat_the_whole_run(harness, monkeypatch):
    engine = harness
    settings_module.set_cache({"INTAKE_MAX_PER_SOURCE": "3", "INTAKE_MAX_PER_RUN": "100"})
    monkeypatch.setattr(
        pipeline_module,
        "SOURCES",
        {"himalayas": lambda ctx, kw: [_job(f"j{n}") for n in range(10)]},
    )

    pipeline_module.run_pipeline("manual")

    assert len(_queued_ids(engine)) == 3


def test_the_run_budget_caps_the_total_across_sources(harness, monkeypatch):
    engine = harness
    settings_module.set_cache({"INTAKE_MAX_PER_SOURCE": "10", "INTAKE_MAX_PER_RUN": "4"})
    monkeypatch.setattr(
        pipeline_module,
        "SOURCES",
        {
            "himalayas": lambda ctx, kw: [_job(f"a{n}") for n in range(5)],
            "weworkremotely": lambda ctx, kw: [_job(f"b{n}") for n in range(5)],
        },
    )

    pipeline_module.run_pipeline("manual")

    assert len(_queued_ids(engine)) == 4


def test_companies_are_walked_before_feeds(harness, monkeypatch):
    """First wins on a duplicate, so the walk order is what decides which copy survives:
    the board's original, not the feed's syndication."""
    order: list[str] = []

    def company_source(ctx, kw):
        order.append("companies")
        return [_job("shared")]

    def feed_source(ctx, kw):
        order.append("himalayas")
        return [_job("shared")]

    # Registered feed-first on purpose: the pipeline must reorder, not rely on the dict.
    monkeypatch.setattr(
        pipeline_module, "SOURCES", {"himalayas": feed_source, "companies": company_source}
    )

    pipeline_module.run_pipeline("manual")

    assert order == ["companies", "himalayas"]


def test_the_run_reports_what_each_source_offered_kept_and_dropped(harness, monkeypatch):
    """A filter set too tight and a dead source are indistinguishable without these."""
    engine = harness
    monkeypatch.setattr(
        pipeline_module,
        "SOURCES",
        {
            "himalayas": lambda ctx, kw: [
                _job("keep"),
                _job("drop", title="Warehouse Picker", description="pallets"),
            ]
        },
    )

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        events = session.exec(select(RunEvent)).all()
    gate = [event for event in events if event.stage == "scrape.himalayas.gate"]
    assert gate, f"no gate event emitted; stages were {_stages(engine)}"
    assert "2" in gate[0].message and "1" in gate[0].message


def test_a_job_added_by_hand_is_never_filtered(harness):
    """The gate belongs to scraping. save_pending_job is also the manual-add path, where
    dropping a job the user entered themselves would be indefensible."""
    from src.services.intake import save_pending_job

    engine = harness
    with Session(engine) as session:
        result = save_pending_job(
            session, _job("by-hand", title="Warehouse Picker", description="pallets")
        )

    assert result == "queued"


def test_the_same_role_from_two_sources_is_queued_once(harness, monkeypatch):
    """Identity within a source is its id; across sources it is the fingerprint. The
    board posting and the feed's syndication of it share nothing but the words."""
    engine = harness

    def company_source(ctx, kw):
        return [
            PendingJobRequest(
                id="greenhouse_acme_1",
                title="Python Developer",
                company="Acme, Inc.",
                location="Remote",
                applylink="https://boards.greenhouse.io/acme/jobs/1",
                description="python django postgres — the original posting",
                website="Greenhouse",
            )
        ]

    def feed_source(ctx, kw):
        return [
            PendingJobRequest(
                id="himalayas_99",
                title="Python Developer",
                company="ACME",
                location="Remote",
                applylink="https://himalayas.app/jobs/99",
                description="python django postgres — a truncated syndication",
                website="Himalayas",
            )
        ]

    monkeypatch.setattr(
        pipeline_module, "SOURCES", {"himalayas": feed_source, "companies": company_source}
    )

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        jobs = session.exec(select(FilteredJob)).all()
    assert len(jobs) == 1
    # First wins, and companies are walked first, so the surviving copy is the original
    # with the real application form rather than the feed's redirect.
    assert jobs[0].id == "greenhouse_acme_1"


def test_a_company_name_with_a_legal_suffix_is_the_same_company(harness, monkeypatch):
    """The blocklist is exact-match today, so "Acme" blocked leaves "Acme, Inc." arriving
    every night. One normalisation, used by the fingerprint and the blocklist alike."""
    from src.services.identity import normalise_company

    assert normalise_company("Acme, Inc.") == normalise_company("ACME")
    assert normalise_company("Acme Group Ltd") == "acme"
    assert normalise_company("Stripe") != normalise_company("Stripes")


def test_blocking_a_company_survives_its_legal_suffix(harness):
    """The blocklist is the one loop the user relies on daily. Exact matching meant
    blocking "Acme" left "Acme, Inc." arriving every night."""
    from src.database.models import BlockedCompany
    from src.services.intake import save_pending_job

    engine = harness
    with Session(engine) as session:
        session.add(BlockedCompany(company_name="acme"))
        session.commit()

        job = _job("j1")
        job.company = "Acme, Inc."
        assert save_pending_job(session, job) == "blocked"


def test_the_gate_reports_its_two_drop_reasons_separately(harness, monkeypatch):
    """Irrelevant and over-budget are different problems with different fixes."""
    engine = harness
    settings_module.set_cache({"INTAKE_MAX_PER_SOURCE": "1", "INTAKE_MAX_PER_RUN": "100"})
    monkeypatch.setattr(
        pipeline_module,
        "SOURCES",
        {
            "himalayas": lambda ctx, kw: [
                _job("keep1"),
                _job("keep2"),
                _job("nope", title="Warehouse Picker", description="pallets"),
            ]
        },
    )

    pipeline_module.run_pipeline("manual")

    with Session(engine) as session:
        gate = [
            event
            for event in session.exec(select(RunEvent)).all()
            if event.stage == "scrape.himalayas.gate"
        ][0]
    assert "1 as irrelevant" in gate.message
    assert "1 over the cap" in gate.message


def test_a_cv_with_no_keywords_says_so_rather_than_dropping_everything_quietly(
    harness, monkeypatch
):
    """Empty keywords make prefilter score every job zero, so every feed job is dropped.
    That looks exactly like every feed being dead unless the run says otherwise."""
    engine = harness
    monkeypatch.setattr(
        pipeline_module, "extract_or_get_keywords", lambda ctx: ("cv text", {})
    )
    monkeypatch.setattr(
        pipeline_module, "SOURCES", {"himalayas": lambda ctx, kw: [_job("a"), _job("b")]}
    )

    pipeline_module.run_pipeline("manual")

    assert _queued_ids(engine) == set()
    assert "keywords.empty" in _stages(engine)


def test_jobs_already_seen_do_not_eat_the_budget(harness, monkeypatch):
    """The cap has to be spent on jobs that can actually be queued.

    A feed returns its best matches in much the same order every night. If the cap is
    applied before the already-seen check, those same jobs fill it every run and a newly
    posted job sitting below the cut never gets in — the queue quietly stops growing
    while the run history still reports a healthy "kept N".
    """
    engine = harness
    settings_module.set_cache({"INTAKE_MAX_PER_SOURCE": "2", "INTAKE_MAX_PER_RUN": "100"})

    old = [_job(f"old{n}") for n in range(2)]
    monkeypatch.setattr(pipeline_module, "SOURCES", {"himalayas": lambda ctx, kw: list(old)})
    pipeline_module.run_pipeline("manual")
    assert _queued_ids(engine) == {"old0", "old1"}

    # Same feed tomorrow: the two from yesterday, plus one new posting behind them.
    monkeypatch.setattr(
        pipeline_module, "SOURCES", {"himalayas": lambda ctx, kw: [*old, _job("fresh")]}
    )
    pipeline_module.run_pipeline("manual")

    assert "fresh" in _queued_ids(engine), (
        "a new posting never entered the queue: the two already-seen jobs consumed the cap"
    )


def test_the_cap_keeps_the_front_of_what_a_source_returns(harness, monkeypatch):
    """The cap truncates, so the order a source hands its jobs over in decides which ones
    are queued. That is the contract: sources return newest first — see
    test_board_parsers.py, which pins each parser to it — and the pipeline keeps the head.
    """
    engine = harness
    settings_module.set_cache({"INTAKE_MAX_PER_SOURCE": "2", "INTAKE_MAX_PER_RUN": "100"})
    monkeypatch.setattr(
        pipeline_module,
        "SOURCES",
        {"companies": lambda ctx, kw: [_job("newest"), _job("middle"), _job("oldest")]},
    )

    pipeline_module.run_pipeline("manual")

    assert _queued_ids(engine) == {"newest", "middle"}
