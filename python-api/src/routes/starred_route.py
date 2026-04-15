from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..database import get_session
from ..database.repositories.starred_companies import StarredCompanyRepository
from .requests_scheme.starred import StarredCompanyCreate, StarredCompanyUpdate, StarredCompanyToggle

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
def add_starred(body: StarredCompanyCreate, session: Session = Depends(get_session)):
    repo = StarredCompanyRepository(session)
    if repo.is_starred(body.company_name):
        raise HTTPException(status_code=409, detail="Company already starred")
    entry = repo.add(
        company_name=body.company_name,
        careers_url=body.careers_url,
        notes=body.notes,
    )
    session.commit()
    session.refresh(entry)
    return entry.model_dump()


@starred_router.delete("/{id}")
def delete_starred(id: int, session: Session = Depends(get_session)):
    deleted = StarredCompanyRepository(session).delete(id)
    if deleted:
        session.commit()
    return {"status": "ok"}


@starred_router.patch("/{id}")
def update_starred(id: int, body: StarredCompanyUpdate, session: Session = Depends(get_session)):
    updated = StarredCompanyRepository(session).update(id, body.careers_url, body.notes)
    if not updated:
        raise HTTPException(status_code=404, detail="Starred company not found")
    session.commit()
    return {"status": "ok"}


@starred_router.post("/toggle")
def toggle_starred(body: StarredCompanyToggle, session: Session = Depends(get_session)):
    is_starred, _ = StarredCompanyRepository(session).toggle(body.company_name)
    session.commit()
    return {"is_starred": is_starred}
