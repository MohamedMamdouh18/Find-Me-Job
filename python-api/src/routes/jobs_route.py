from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from ..database import get_session
from ..database.models import PendingJob
from ..database.repositories import PendingJobRepository, SeenJobRepository

jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class PendingJobRequest(BaseModel):
    id: str
    title: str
    company: str
    location: str
    applylink: str
    description: str
    website: str


@jobs_router.get("/exists")
def job_exists(jobid: str, session: Session = Depends(get_session)):
    exists = (
        PendingJobRepository(session).exists(jobid)
        or SeenJobRepository(session).exists(jobid)
    )
    return {"exists": exists}


@jobs_router.post("/pending")
def add_pending_job(job: PendingJobRequest, session: Session = Depends(get_session)):
    PendingJobRepository(session).add(PendingJob(**job.model_dump()))
    session.commit()
    return {"status": "ok"}


@jobs_router.post("/job/complete")
def complete_job(jobid: str, session: Session = Depends(get_session)):
    pending_repo = PendingJobRepository(session)
    if not pending_repo.exists(jobid):
        raise HTTPException(status_code=404, detail=f"Job {jobid} not found in pending_jobs")

    SeenJobRepository(session).add(jobid)
    pending_repo.delete(jobid)
    session.commit()
    return {"status": "ok", "jobid": jobid}


@jobs_router.get("/pending")
def get_pending_jobs(session: Session = Depends(get_session)):
    jobs = PendingJobRepository(session).get_all()
    return {"rows": [job.model_dump() for job in jobs]}
