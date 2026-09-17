"""Editing CV keywords from the dashboard.

The rule this file guards: an edit is stored against the current CV's hash, so the next
run keeps it instead of paying for a fresh extraction and overwriting the user's work.
"""

import json

import docx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool

import src.database.models  # noqa: F401
from src.database.core import get_session
from src.database.models import CVKeywords
from src.main import app
from src.routes import cv_route
from src.services import keywords as keywords_service
from src.services.keywords import extract_or_get_keywords
from src.services.run_context import RunContext


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def cv_file(tmp_path, monkeypatch):
    path = tmp_path / "cv.docx"
    doc = docx.Document()
    doc.add_paragraph("Backend engineer. Python, FastAPI, SQL.")
    doc.save(str(path))
    monkeypatch.setattr(cv_route, "CV_PATH", str(path))
    return path


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


def _stored(engine) -> dict:
    with Session(engine) as session:
        row = session.exec(select(CVKeywords)).one()
        return json.loads(row.keywords)


def test_put_saves_cleaned_lists(client, engine, cv_file):
    res = client.put("/api/cv/keywords", json={
        "titles": [" Backend Engineer ", "backend engineer", ""],
        "skills": ["Python", "python", "  ", "Kubernetes"],
    })
    assert res.status_code == 200
    assert _stored(engine) == {"titles": ["Backend Engineer"], "skills": ["Python", "Kubernetes"]}
    assert json.loads(client.get("/api/cv/keywords").json()["keywords"])["skills"] == ["Python", "Kubernetes"]


def test_edited_keywords_survive_the_next_run(client, engine, cv_file, monkeypatch):
    client.put("/api/cv/keywords", json={"titles": ["Platform Engineer"], "skills": ["Go"]})

    def no_llm(*args, **kwargs):
        raise AssertionError("an edited keyword set must not be re-extracted")

    monkeypatch.setattr(keywords_service, "call_llm", no_llm)
    with Session(engine) as session:
        _, kw = extract_or_get_keywords(RunContext(1, session), cv_path=str(cv_file))
    assert kw == {"titles": ["Platform Engineer"], "skills": ["Go"]}


def test_clearing_both_lists_is_stored_not_re_extracted(client, engine, cv_file):
    assert client.put("/api/cv/keywords", json={"titles": [], "skills": []}).status_code == 200
    assert _stored(engine) == {"titles": [], "skills": []}


def test_save_moves_updated_at(client, engine, cv_file):
    client.put("/api/cv/keywords", json={"titles": ["A"], "skills": []})
    first = client.get("/api/cv/keywords").json()["updated_at"]
    client.put("/api/cv/keywords", json={"titles": ["B"], "skills": []})
    assert client.get("/api/cv/keywords").json()["updated_at"] > first


def test_delete_forgets_keywords(client, engine, cv_file):
    client.put("/api/cv/keywords", json={"titles": ["A"], "skills": ["B"]})
    assert client.delete("/api/cv/keywords").json() == {"deleted": True}
    assert client.get("/api/cv/keywords").json()["keywords"] is None
    assert client.delete("/api/cv/keywords").json() == {"deleted": False}


def test_put_without_a_cv_is_refused(client, tmp_path, monkeypatch):
    monkeypatch.setattr(cv_route, "CV_PATH", str(tmp_path / "missing.docx"))
    res = client.put("/api/cv/keywords", json={"titles": ["A"], "skills": []})
    assert res.status_code == 409


@pytest.mark.parametrize("body", [
    {"titles": ["x" * 101], "skills": []},
    {"titles": [], "skills": [f"s{i}" for i in range(301)]},
    {"titles": "Backend", "skills": []},
    {"skills": []},
])
def test_put_rejects_bad_payloads(client, cv_file, body):
    assert client.put("/api/cv/keywords", json=body).status_code == 422
