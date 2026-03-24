from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..database import get_session
from ..database.models import FilteredJob, PendingJob
from ..database.repositories import FilteredJobRepository, PendingJobRepository, SeenJobRepository
from .requests_scheme.jobs import PendingJobRequest, FilteredJobRequest, StatusUpdate

jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@jobs_router.get("/exists")
def job_exists(jobid: str, session: Session = Depends(get_session)):
    exists = SeenJobRepository(session).exists(jobid)
    return {"exists": exists}


@jobs_router.post("/pending")
def add_pending_job(job: PendingJobRequest, session: Session = Depends(get_session)):
    SeenJobRepository(session).add(job.id)
    PendingJobRepository(session).add(PendingJob(**job.model_dump()))
    session.commit()
    return {"status": "ok"}


@jobs_router.post("/filtered")
def add_filtered_job(job: FilteredJobRequest, session: Session = Depends(get_session)):
    PendingJobRepository(session).delete(job.id)
    FilteredJobRepository(session).add(FilteredJob(**job.model_dump()))
    session.commit()
    return {"status": "ok"}


@jobs_router.get("/filtered/{jobid}")
def get_filtered_job(jobid: str, session: Session = Depends(get_session)):
    job = FilteredJobRepository(session).get(jobid)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {jobid} not found")
    return job.model_dump()


@jobs_router.patch("/filtered/{jobid}/status")
def update_job_status(jobid: str, body: StatusUpdate, session: Session = Depends(get_session)):
    updated = FilteredJobRepository(session).update_status(jobid, body.user_status)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Job {jobid} not found")
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
