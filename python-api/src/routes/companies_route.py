import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session

from ..database import get_session
from ..database.core import engine
from ..database.repositories.companies import CompanyRepository
from ..schemas.companies import CompanyUpdate
from ..scrapers.companies import detect, fetch_company
from ..services import settings
from ..services.intake import save_pending_job

logger = logging.getLogger(__name__)

companies_router = APIRouter(prefix="/api/companies", tags=["companies"])

UNCHECKED = {"fetch_method": "unknown", "ats": None, "ats_token": None, "fetch_note": None}


def _row(company) -> dict:
    return {
        "id": company.id,
        "company_name": company.company_name,
        "careers_url": company.careers_url,
        "notes": company.notes,
        "starred": company.starred,
        "in_workflow": company.in_workflow,
        "fetch_method": company.fetch_method,
        "fetch_note": company.fetch_note,
        "ats": company.ats,
        "last_scraped_at": company.last_scraped_at,
        "last_job_count": company.last_job_count,
    }


def _detect_in_background(company_id: int) -> None:
    """Detection fetches a third-party page, so it never runs inside the request that
    saves the URL: the write returns immediately with `unknown` and the verdict lands
    after. Its own session, because the request's is closed by then."""
    with Session(engine) as session:
        repo = CompanyRepository(session)
        company = repo.get(company_id)
        if not company or not company.careers_url:
            return
        try:
            verdict = detect(company.careers_url)
        except Exception as e:
            logger.warning(f"Detection failed for {company.company_name}: {e}")
            verdict = {
                "fetch_method": "unreadable",
                "fetch_note": f"The page could not be checked: {e}",
            }
        repo.set_detection(company, verdict)
        session.commit()


@companies_router.get("")
def list_companies(session: Session = Depends(get_session)):
    return [_row(company) for company in CompanyRepository(session).get_all()]


@companies_router.patch("/{company_id}")
def update_company(
    company_id: int,
    body: CompanyUpdate,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    repo = CompanyRepository(session)
    company = repo.get(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    if body.careers_url is not None and body.careers_url != company.careers_url:
        company.careers_url = body.careers_url or None
        # The verdict belongs to the URL, so a new URL starts from not-checked-yet.
        repo.set_detection(company, dict(UNCHECKED))
        background.add_task(_detect_in_background, company_id)

    if body.starred is not None:
        company.starred = body.starred

    if body.in_workflow is not None and not repo.set_in_workflow(company, body.in_workflow):
        raise HTTPException(
            status_code=409,
            detail=(
                "This company cannot be put in the workflow yet: "
                f"{company.fetch_note or 'its careers page has not been checked.'}"
            ),
        )

    session.add(company)
    session.commit()
    session.refresh(company)
    return _row(company)


@companies_router.post("/{company_id}/scrape")
def scrape_company(company_id: int, session: Session = Depends(get_session)):
    """Fetch one company now, whatever its switch says.

    Writes through the single intake path, so the blocklist, seen jobs and the
    fingerprint all apply — including a company both listed and blocked, which intake
    resolves by blocking. Opens no workflow_runs row: this is not a run, and the pipeline
    stays the only writer of run state.
    """
    repo = CompanyRepository(session)
    company = repo.get(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    try:
        jobs = fetch_company(company)
    except Exception as e:
        logger.warning(f"On-demand scrape failed for {company.company_name}: {e}")
        raise HTTPException(status_code=502, detail=f"Could not fetch this company: {e}")

    # The per-source ceiling applies here too. Without it one board can queue hundreds of
    # jobs that the next run then has to drain at SCORING_DELAY_SECONDS apiece — the exact
    # thing the gate exists to prevent, arriving through a different door.
    ceiling = settings.get_intake_max_per_source()
    counts = {"queued": 0, "already_seen": 0, "blocked": 0}
    for job in jobs[:ceiling]:
        counts[save_pending_job(session, job)] += 1

    # Only a fetch that actually happened counts towards the empty streak. A company whose
    # page has not been checked, or cannot be read, returns [] without making a request —
    # counting that would mark it "returned no jobs twice" for something it never did.
    if company.fetch_method in ("ats", "page"):
        repo.record_fetch(company, len(jobs))
    session.commit()
    return {
        **counts,
        "found": len(jobs),
        "over_cap": max(len(jobs) - ceiling, 0),
        "fetch_method": company.fetch_method,
    }


@companies_router.post("/{company_id}/detect")
def redetect_company(
    company_id: int, background: BackgroundTasks, session: Session = Depends(get_session)
):
    """Check the careers URL again — a page that was unreadable may have been redesigned."""
    repo = CompanyRepository(session)
    company = repo.get(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if not company.careers_url:
        raise HTTPException(status_code=400, detail="This company has no careers URL")

    repo.set_detection(company, dict(UNCHECKED))
    session.commit()
    background.add_task(_detect_in_background, company_id)
    return {"status": "checking"}
