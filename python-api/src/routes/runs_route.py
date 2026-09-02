import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from ..database import get_session
from ..database.models import WorkflowRun
from ..database.repositories import WorkflowRunRepository, RunEventRepository
from ..services.pipeline import run_pipeline
from ..services.run_context import get_current_progress
from ..shared import now, scheduler
from ..schemas.runs import RunStart, RunFinish

logger = logging.getLogger(__name__)
runs_router = APIRouter(prefix="/api/runs", tags=["runs"])


@runs_router.get("")
def list_runs(limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_session)):
    return [r.model_dump() for r in WorkflowRunRepository(session).get_recent(limit)]


@runs_router.post("/trigger", status_code=202)
def trigger_run():
    """Triggers an immediate background execution of the scraping and scoring pipeline."""
    scheduler.add_job(run_pipeline, "date", run_date=now(), args=["manual"])
    return {"status": "triggered"}


@runs_router.get("/current")
def get_current_run_progress(session: Session = Depends(get_session)) -> Any:
    """Returns the live in-process progress and countdown if a run is active, or null (200 OK)."""
    p = get_current_progress()
    if p is not None:
        seconds_remaining = None
        if p.waiting_until is not None:
            diff = (p.waiting_until - now()).total_seconds()
            seconds_remaining = max(0, int(diff))

        recent_events = [
            e.model_dump()
            for e in RunEventRepository(session).get_by_run_id(p.run_id, limit=5)
        ]

        return {
            "run_id": p.run_id,
            "stage": p.stage,
            "detail": p.detail,
            "done": p.done,
            "total": p.total,
            "waiting_until": p.waiting_until.isoformat() if p.waiting_until else None,
            "seconds_remaining": seconds_remaining,
            "events": recent_events,
        }

    # Fallback to database if process restarted mid-run
    running = session.exec(
        select(WorkflowRun)
        .where(WorkflowRun.status == "running")
        .order_by(WorkflowRun.started_at.desc())  # type: ignore[arg-type]
    ).first()

    if running:
        recent_events = [
            e.model_dump()
            for e in RunEventRepository(session).get_by_run_id(running.id, limit=5)
        ]
        return {
            "run_id": running.id,
            "stage": running.stage or "running",
            "detail": running.stage_detail or "In progress",
            "done": 0,
            "total": 0,
            "waiting_until": None,
            "seconds_remaining": None,
            "events": recent_events,
        }

    return None


@runs_router.get("/{run_id}/events")
def get_run_events(run_id: int, session: Session = Depends(get_session)):
    """Returns the complete event history for a run."""
    events = RunEventRepository(session).get_by_run_id(run_id)
    return [e.model_dump() for e in events]


@runs_router.post("/start", status_code=201)
def start_run(body: RunStart, session: Session = Depends(get_session)):
    run = WorkflowRunRepository(session).start(trigger=body.trigger)
    session.commit()
    session.refresh(run)
    return run.model_dump()


@runs_router.post("/{run_id}/finish")
def finish_run(run_id: int, body: RunFinish, session: Session = Depends(get_session)):
    run = WorkflowRunRepository(session).finish(
        run_id, status=body.status, error=body.error, jobs_scraped=body.jobs_scraped
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    session.commit()
    session.refresh(run)
    return run.model_dump()
