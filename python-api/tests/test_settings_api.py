"""The generic settings endpoints: masking, partial updates, validation, recompute.

The table is untyped, the API is unauthenticated and the tunnel exposes the dashboard
publicly, so two things are load-bearing here and both are tested through HTTP rather
than by reading the registry: a stored secret is never echoed, and an invalid value is
a 400 naming the key instead of a row that kills the next boot.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool

import src.database.models  # noqa: F401
from src.database.core import get_session
from src.database.models import FilteredJob, JobStatusHistory
from src.database.models.enums import AiStatus, UserStatus
from src.database.repositories import AppSettingRepository
from src.main import app
from src.services import settings


@pytest.fixture(autouse=True)
def clean_cache():
    settings.set_cache({})
    yield
    settings.set_cache({})


@pytest.fixture
def client(monkeypatch):
    # The endpoints read through the cache, which falls back to the environment;
    # a stray .env value in the test container would make assertions depend on it.
    for key in settings.SETTINGS:
        monkeypatch.delenv(key, raising=False)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

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


def _job(job_id: str, score: int, status: AiStatus) -> FilteredJob:
    return FilteredJob(
        id=job_id,
        title="Engineer",
        company="Acme",
        location="Remote",
        applylink="https://example.com",
        description="d",
        score=score,
        ai_status=status,
        user_status=UserStatus.NEW,
        website="LinkedIn",
    )


def test_get_returns_effective_values(client):
    body = client.get("/api/settings").json()

    assert body["LLM_MODEL"] == "gemini-2.5-flash"
    assert body["FILTERING_SCORE"] == 60
    assert body["AUTO_EMAIL"] is False
    assert body["SMTP_PORT"] == 587
    # Schedule keys are readable here even though they are written elsewhere.
    assert body["PIPELINE_AT_TIME"] == "01:00"


def test_secrets_are_never_returned(client):
    client.put("/api/settings", json={"LLM_API_KEY": "sk-abcdefgh1234"})

    res = client.get("/api/settings")
    body = res.json()
    assert body["LLM_API_KEY"] == {"set": True, "hint": "…1234"}
    assert "sk-abcdefgh1234" not in res.text

    # And an unset secret says so rather than returning an empty string.
    assert body["TELEGRAM_BOT_TOKEN"] == {"set": False}


def test_a_secret_too_short_to_hint_gets_no_hint(client):
    """The hint exists to tell two keys apart. On a short value its last characters
    are the value, so the endpoint would be echoing the credential it is masking."""
    client.put("/api/settings", json={"LLM_API_KEY": "sk12"})

    res = client.get("/api/settings")
    assert res.json()["LLM_API_KEY"] == {"set": True, "hint": ""}
    assert "sk12" not in res.text


def test_partial_update_writes_only_what_it_names(client):
    client.put("/api/settings", json={"LLM_MODEL": "gpt-4o-mini"})

    with Session(client.engine) as session:
        stored = AppSettingRepository(session).get_all()
    assert stored == {"LLM_MODEL": "gpt-4o-mini"}


def test_invalid_value_is_a_400_naming_the_key(client):
    res = client.put("/api/settings", json={"FILTERING_SCORE": "200"})

    assert res.status_code == 400
    assert "FILTERING_SCORE" in res.json()["detail"]

    with Session(client.engine) as session:
        assert AppSettingRepository(session).get_all() == {}


def test_unknown_key_is_rejected(client):
    res = client.put("/api/settings", json={"NOT_A_SETTING": "1"})

    assert res.status_code == 400
    assert "NOT_A_SETTING" in res.json()["detail"]


def test_schedule_keys_are_refused_by_the_generic_endpoint(client):
    res = client.put("/api/settings", json={"PIPELINE_AT_TIME": "02:00"})

    assert res.status_code == 400
    assert "/api/settings/schedule" in res.json()["detail"]


def test_blank_secret_leaves_the_stored_value_alone(client):
    client.put("/api/settings", json={"SMTP_APP_PASSWORD": "hunter2hunter2"})
    client.put("/api/settings", json={"SMTP_APP_PASSWORD": "", "SENDER_NAME": "Ada"})

    with Session(client.engine) as session:
        stored = AppSettingRepository(session).get_all()
    assert stored["SMTP_APP_PASSWORD"] == "hunter2hunter2"
    assert stored["SENDER_NAME"] == "Ada"


def test_null_clears_a_secret(client):
    client.put("/api/settings", json={"SMTP_APP_PASSWORD": "hunter2hunter2"})
    client.put("/api/settings", json={"SMTP_APP_PASSWORD": None})

    assert client.get("/api/settings").json()["SMTP_APP_PASSWORD"] == {"set": False}


def test_a_blank_non_secret_is_a_real_value(client):
    client.put("/api/settings", json={"SENDER_NAME": "Ada"})
    client.put("/api/settings", json={"SENDER_NAME": ""})

    assert client.get("/api/settings").json()["SENDER_NAME"] == ""


def test_lowering_the_cutoff_reclassifies_and_reports(client):
    with Session(client.engine) as session:
        session.add(_job("a", 55, AiStatus.NOT_FIT))
        session.add(_job("b", 75, AiStatus.FIT))
        session.add(_job("c", 40, AiStatus.NOT_FIT))
        session.commit()

    res = client.put("/api/settings", json={"FILTERING_SCORE": 50})

    assert res.status_code == 200
    assert res.json()["reclassified"] == 1

    with Session(client.engine) as session:
        statuses = {job.id: job.ai_status for job in session.exec(select(FilteredJob)).all()}
    assert statuses == {"a": AiStatus.FIT, "b": AiStatus.FIT, "c": AiStatus.NOT_FIT}


def test_raising_the_cutoff_reclassifies_downwards(client):
    with Session(client.engine) as session:
        session.add(_job("a", 65, AiStatus.FIT))
        session.commit()

    res = client.put("/api/settings", json={"FILTERING_SCORE": 70})
    assert res.json()["reclassified"] == 1

    with Session(client.engine) as session:
        assert session.get(FilteredJob, "a").ai_status == AiStatus.NOT_FIT


def test_reclassify_does_not_touch_user_status_or_history(client):
    with Session(client.engine) as session:
        job = _job("a", 55, AiStatus.NOT_FIT)
        job.user_status = UserStatus.APPLIED
        session.add(job)
        session.commit()
        before = session.get(FilteredJob, "a").updated_at

    client.put("/api/settings", json={"FILTERING_SCORE": 50})

    with Session(client.engine) as session:
        job = session.get(FilteredJob, "a")
        assert job.user_status == UserStatus.APPLIED
        assert job.updated_at == before
        assert session.exec(select(JobStatusHistory)).all() == []


def test_a_write_reaches_the_next_reader_without_a_restart(client):
    client.put("/api/settings", json={"SCORING_DELAY_SECONDS": 5})

    assert settings.get_scoring_delay() == 5
