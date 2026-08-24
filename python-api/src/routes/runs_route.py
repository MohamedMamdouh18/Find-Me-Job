from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from ..database import get_session
from ..database.repositories import WorkflowRunRepository
from .requests_scheme.runs import RunStart, RunFinish

runs_router = APIRouter(prefix="/api/runs", tags=["runs"])


@runs_router.get("")
def list_runs(limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_session)):
    return [r.model_dump() for r in WorkflowRunRepository(session).get_recent(limit)]


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
