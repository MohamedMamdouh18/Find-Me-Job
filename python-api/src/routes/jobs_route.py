import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import Session

from ..database import get_session
from ..database.models import FilteredJob, PendingJob
from ..database.models.enums import AiStatus, UserStatus
from ..database.repositories import (
    BlockedCompanyRepository,
    CVKeywordsRepository,
    FilteredJobRepository,
    PendingJobRepository,
    SeenJobRepository,
)
from ..services.match_evidence import evidence, matched_skills, parse_keywords
from ..shared import now
from .requests_scheme.jobs import PendingJobRequest, FilteredJobRequest, StatusUpdate

jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@jobs_router.get("/exists")
def job_exists(
    jobid: str, company: Optional[str] = None, session: Session = Depends(get_session)
):
    """`skip` is what scrapers should branch on: already seen, or the company is blocked."""
    exists = SeenJobRepository(session).exists(jobid)
    blocked = BlockedCompanyRepository(session).is_blocked(company) if company else False
    return {"exists": exists, "blocked": blocked, "skip": exists or blocked}


@jobs_router.post("/pending")
def add_pending_job(job: PendingJobRequest, session: Session = Depends(get_session)):
    # Blocklist is enforced here rather than in the scrapers, so every source gets it
    # for free and a blocked company never costs an LLM call. The job is still recorded
    # as seen so it is not re-fetched on every subsequent run.
    if BlockedCompanyRepository(session).is_blocked(job.company):
        SeenJobRepository(session).add(job.id)
        session.commit()
        return {"status": "blocked", "company": job.company}

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


CLEAR_ALL_TOKEN = "delete-all-jobs"


@jobs_router.delete("/filtered")
def delete_all_filtered_jobs(
    confirm: str = Query(..., description=f"Must be '{CLEAR_ALL_TOKEN}'"),
    session: Session = Depends(get_session),
):
    """Wipe the jobs table. Guarded by an explicit token so a stray DELETE cannot
    empty the database — the dashboard also asks the user to type the phrase."""
    if confirm != CLEAR_ALL_TOKEN:
        raise HTTPException(status_code=400, detail="Missing or wrong confirmation token")
    deleted = FilteredJobRepository(session).delete_all()
    session.commit()
    return {"deleted": deleted}


@jobs_router.delete("/filtered/{jobid}")
def delete_filtered_job(jobid: str, session: Session = Depends(get_session)):
    deleted = FilteredJobRepository(session).delete(jobid)
    if deleted:
        session.commit()
    return {"status": "ok"}


@jobs_router.get("/filtered/{jobid}/match")
def get_job_match_evidence(jobid: str, session: Session = Depends(get_session)):
    """Which CV skills this posting names. Not the scorer's reasoning — the model
    only ever returns a number and a cover letter — so the caller must say so."""
    job = FilteredJobRepository(session).get(jobid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _, skills = parse_keywords(_latest_keywords(session))
    return evidence(job.description, skills)


def _latest_keywords(session: Session) -> str | None:
    row = CVKeywordsRepository(session).get_latest()
    return row.keywords if row else None


@jobs_router.get("/filtered/{jobid}/history")
def get_filtered_job_history(jobid: str, session: Session = Depends(get_session)):
    return FilteredJobRepository(session).get_status_history(jobid)


@jobs_router.get("/pending/count")
def count_pending_jobs(session: Session = Depends(get_session)):
    """Queue depth for the dashboard status strip — a count, never the rows."""
    return {"count": PendingJobRepository(session).count()}


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
    max_score: Optional[int] = None,
    search: Optional[str] = None,
    company: Optional[str] = None,
    website: Optional[str] = None,
    location: Optional[str] = None,
    starred_only: bool = False,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    include_body: bool = True,
    include_keywords: bool = False,
    session: Session = Depends(get_session),
):
    repo = FilteredJobRepository(session)
    jobs, total = repo.get_all(
        ai_status=ai_status,
        user_status=user_status,
        easy_apply=easy_apply,
        min_score=min_score,
        max_score=max_score,
        search=search,
        company=company,
        website=website,
        location=location,
        starred_only=starred_only,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
        include_body=include_body,
    )
    if include_body:
        rows = [job.model_dump() for job in jobs]
    else:
        rows = [job.model_dump(exclude={"description", "application_document"}) for job in jobs]

    if include_keywords:
        _, skills = parse_keywords(_latest_keywords(session))
        # The list query drops the description on purpose, so the blobs for just
        # this page are fetched separately rather than by widening the query.
        bodies = repo.get_descriptions([r["id"] for r in rows]) if skills else {}
        for row in rows:
            row["keywords"] = matched_skills(bodies.get(row["id"]), skills)

    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": -(-total // page_size),  # ceiling division
    }


EXPORT_COLUMNS = [
    "id",
    "title",
    "company",
    "location",
    "website",
    "score",
    "ai_status",
    "user_status",
    "easy_apply",
    "applylink",
    "created_at",
    "updated_at",
]


@jobs_router.get("/export")
def export_jobs(
    format: str = Query("csv", pattern="^(csv|json)$"),
    ai_status: Optional[AiStatus] = None,
    user_status: Optional[UserStatus] = None,
    min_score: Optional[int] = None,
    include_body: bool = False,
    session: Session = Depends(get_session),
):
    """Export the filtered jobs table. Streams so a large table never sits in memory twice."""
    repo = FilteredJobRepository(session)
    jobs, _ = repo.get_all(
        ai_status=ai_status,
        user_status=user_status,
        min_score=min_score,
        page=1,
        page_size=100_000,
        include_body=include_body,
    )

    columns = EXPORT_COLUMNS + (["description", "application_document"] if include_body else [])
    stamp = now().strftime("%Y%m%d-%H%M%S")

    if format == "json":
        rows = [
            {c: _serialise(getattr(job, c, None)) for c in columns}
            for job in jobs
        ]
        return JSONResponse(
            rows,
            headers={"Content-Disposition": f'attachment; filename="jobs-{stamp}.json"'},
        )

    def rows_iter():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(columns)
        yield buffer.getvalue()
        for job in jobs:
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow([_serialise(getattr(job, c, None)) for c in columns])
            yield buffer.getvalue()

    return StreamingResponse(
        rows_iter(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="jobs-{stamp}.csv"'},
    )


def _serialise(value):
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):  # enum
        return value.value
    return value


@jobs_router.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    return FilteredJobRepository(session).get_stats()


@jobs_router.get("/stats/daily-applied")
def get_daily_applied(days: int = Query(7, ge=1, le=730), session: Session = Depends(get_session)):
    return FilteredJobRepository(session).get_daily_applied(days)


@jobs_router.get("/stats/by-source")
def get_stats_by_source(session: Session = Depends(get_session)):
    return FilteredJobRepository(session).get_stats_by_source()


@jobs_router.get("/stats/score-distribution")
def get_score_distribution(session: Session = Depends(get_session)):
    return FilteredJobRepository(session).get_score_distribution()


@jobs_router.get("/stats/funnel")
def get_funnel(session: Session = Depends(get_session)):
    """Arrivals per stage, counted from the status log."""
    return FilteredJobRepository(session).get_funnel()


@jobs_router.get("/stats/top-companies")
def get_top_companies(limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_session)):
    return FilteredJobRepository(session).get_top_companies(limit)
