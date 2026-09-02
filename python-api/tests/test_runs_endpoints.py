from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool

import src.database.models  # noqa: F401
from src.database.core import get_session
from src.database.repositories import WorkflowRunRepository, RunEventRepository
from src.services.run_context import set_current_progress
from src.main import app


def test_runs_routes_and_progress():
    set_current_progress(None)
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
    client = TestClient(app)

    try:
        # 1. Idle progress returns 200 with null
        res_curr = client.get("/api/runs/current")
        assert res_curr.status_code == 200
        assert res_curr.json() is None

        # 2. Trigger run returns 202
        res_trig = client.post("/api/runs/trigger")
        assert res_trig.status_code == 202
        assert res_trig.json() == {"status": "triggered"}

        # 3. Events drilldown
        with Session(engine) as session:
            run = WorkflowRunRepository(session).start(trigger="manual")
            session.commit()
            session.refresh(run)
            RunEventRepository(session).add(
                run_id=run.id,
                stage="score",
                message="Scored job 1",
                level="info",
                context='{"detail": "good"}',
            )
            session.commit()
            run_id = run.id

        res_events = client.get(f"/api/runs/{run_id}/events")
        assert res_events.status_code == 200
        events = res_events.json()
        assert len(events) == 1
        assert events[0]["stage"] == "score"
        assert events[0]["message"] == "Scored job 1"

    finally:
        app.dependency_overrides.clear()
