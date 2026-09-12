import logging
from typing import Any
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from ..database import get_session
from ..database.repositories import WorkflowRunRepository, RunEventRepository
from ..services.pipeline import run_pipeline
from ..services.run_context import get_current_progress
from ..shared import now, scheduler

logger = logging.getLogger(__name__)
runs_router = APIRouter(prefix="/api/runs", tags=["runs"])


@runs_router.get("")
def list_runs(limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_session)):
    runs = WorkflowRunRepository(session).get_recent(limit)
    # Dump before committing: commit expires the instances, and model_dump() reads
    # their attributes without triggering a refresh, so it would return empty rows.
    payload = [r.model_dump() for r in runs]
    # get_recent expires runs that never reported back; repositories never commit.
    session.commit()
    return payload


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
    running = WorkflowRunRepository(session).get_running()

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


# POST /start and POST /{run_id}/finish were removed with n8n. Nothing calls them, and
# /start ran _fail_stale_runs with no time cutoff, so hitting it during a live run flipped
# that run to "failed" while the pipeline kept going. Run bookkeeping is in-process now.
