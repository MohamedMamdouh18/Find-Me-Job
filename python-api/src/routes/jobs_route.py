from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ..database import get_session
from ..database.models import FilteredJob, PendingJob
from ..database.models.enums import AiStatus, UserStatus
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


@jobs_router.get("/filtered/options")
def get_filter_options(session: Session = Depends(get_session)):
    repo = FilteredJobRepository(session)
    return {
        "companies": repo.get_distinct_values("company"),
        "websites": repo.get_distinct_values("website"),
        "locations": repo.get_distinct_values("location"),
    }


@jobs_router.get("/filtered/{jobid}")
def get_filtered_job(jobid: str, session: Session = Depends(get_session)):
    job = FilteredJobRepository(session).get(jobid)
    if not job:
        return {"job": None}
    return job.model_dump()


@jobs_router.patch("/filtered/{jobid}/status")
def update_job_status(jobid: str, body: StatusUpdate, session: Session = Depends(get_session)):
    updated = FilteredJobRepository(session).update_status(jobid, body.user_status)
    if updated:
        session.commit()
    return {"status": "ok"}


@jobs_router.delete("/filtered/{jobid}")
def delete_filtered_job(jobid: str, session: Session = Depends(get_session)):
    deleted = FilteredJobRepository(session).delete(jobid)
    if deleted:
        session.commit()
    return {"status": "ok"}


@jobs_router.get("/filtered/{jobid}/history")
def get_filtered_job_history(jobid: str, session: Session = Depends(get_session)):
    return FilteredJobRepository(session).get_status_history(jobid)


@jobs_router.get("/pending")
def get_pending_jobs(session: Session = Depends(get_session)):
    jobs = PendingJobRepository(session).get_all()
    return {"rows": [job.model_dump() for job in jobs]}


@jobs_router.get("/filtered")
def get_filtered_jobs(
    ai_status: Optional[AiStatus] = None,
    user_status: Optional[UserStatus] = None,
    easy_apply: Optional[bool] = None,
    min_score: Optional[int] = None,
    search: Optional[str] = None,
    company: Optional[str] = None,
    website: Optional[str] = None,
    location: Optional[str] = None,
    starred_only: bool = False,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20,
    session: Session = Depends(get_session),
):
    jobs, total = FilteredJobRepository(session).get_all(
        ai_status=ai_status,
        user_status=user_status,
        easy_apply=easy_apply,
        min_score=min_score,
        search=search,
        company=company,
        website=website,
        location=location,
        starred_only=starred_only,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    return {
        "rows": [job.model_dump() for job in jobs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": -(-total // page_size),  # ceiling division
    }


@jobs_router.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    return FilteredJobRepository(session).get_stats()


@jobs_router.get("/stats/daily-applied")
def get_daily_applied(days: int = 7, session: Session = Depends(get_session)):
    return FilteredJobRepository(session).get_daily_applied(days)


@jobs_router.get("/stats/by-source")
def get_stats_by_source(session: Session = Depends(get_session)):
    return FilteredJobRepository(session).get_stats_by_source()


@jobs_router.get("/stats/scores")
def get_scores(session: Session = Depends(get_session)):
    return FilteredJobRepository(session).get_all_scores()
