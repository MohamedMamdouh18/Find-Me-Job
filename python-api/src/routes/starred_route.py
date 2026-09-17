from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from sqlmodel import Session

from ..database import get_session
from ..database.repositories.companies import CompanyRepository
from ..database.repositories.starred_companies import StarredCompanyRepository
from ..schemas.starred import StarredCompanyCreate, StarredCompanyUpdate, StarredCompanyToggle
from .companies_route import UNCHECKED, _detect_in_background

starred_router = APIRouter(prefix="/api/starred", tags=["starred"])


@starred_router.get("")
def list_starred(search: Optional[str] = None, session: Session = Depends(get_session)):
    entries = StarredCompanyRepository(session).get_all(search=search)
    return [e.model_dump() for e in entries]


@starred_router.get("/names")
def list_starred_names(session: Session = Depends(get_session)):
    """Return all starred company names (lowercase) for bulk client-side checks."""
    return StarredCompanyRepository(session).get_names()


@starred_router.get("/check")
def check_starred(company: str, session: Session = Depends(get_session)):
    return {"is_starred": StarredCompanyRepository(session).is_starred(company)}


@starred_router.post("", status_code=201)
def add_starred(
    body: StarredCompanyCreate,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    repo = StarredCompanyRepository(session)
    if repo.is_starred(body.company_name):
        raise HTTPException(status_code=409, detail="Company already starred")
    entry = repo.add(
        company_name=body.company_name,
        careers_url=body.careers_url,
        notes=body.notes,
    )
    try:
        session.commit()
    except IntegrityError:
        # Another request (a second tab) inserted it between the check and the commit.
        session.rollback()
        raise HTTPException(status_code=409, detail="Company already starred")
    session.refresh(entry)
    # A careers URL is only useful once we know what is behind it, and this is where one
    # arrives. Detection fetches a third-party page, so it runs after the response rather
    # than inside it: the row saves as `unknown` and the verdict lands a moment later.
    if entry.careers_url:
        background.add_task(_detect_in_background, entry.id)
    return entry.model_dump()


@starred_router.delete("/{id}")
def delete_starred(id: int, session: Session = Depends(get_session)):
    deleted = StarredCompanyRepository(session).delete(id)
    if deleted:
        session.commit()
    return {"status": "ok"}


@starred_router.patch("/{id}")
def update_starred(
    id: int,
    body: StarredCompanyUpdate,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    repo = CompanyRepository(session)
    company = repo.get(id)
    url_changed = company is not None and (body.careers_url or None) != company.careers_url

    updated = StarredCompanyRepository(session).update(id, body.careers_url, body.notes)
    if not updated:
        raise HTTPException(status_code=404, detail="Starred company not found")

    if url_changed:
        # The verdict belongs to the URL. Without this reset a company keeps its old
        # board token and goes on reporting healthy jobs from the previous employer.
        repo.set_detection(company, dict(UNCHECKED))
    session.commit()

    if url_changed and company.careers_url:
        background.add_task(_detect_in_background, id)
    return {"status": "ok"}


@starred_router.post("/toggle")
def toggle_starred(body: StarredCompanyToggle, session: Session = Depends(get_session)):
    is_starred, _ = StarredCompanyRepository(session).toggle(body.company_name)
    try:
        session.commit()
    except (IntegrityError, StaleDataError):
        # A concurrent toggle got there first and already produced the state this one
        # was heading for: the insert collided, or the row was already deleted.
        session.rollback()
    return {"is_starred": is_starred}
