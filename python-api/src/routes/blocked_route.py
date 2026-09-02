from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..database import get_session
from ..database.repositories import BlockedCompanyRepository
from ..schemas.blocked import (
    BlockedCompanyCreate,
    BlockedCompanyUpdate,
    BlockedCompanyToggle,
)

blocked_router = APIRouter(prefix="/api/blocked", tags=["blocked"])


@blocked_router.get("")
def list_blocked(search: Optional[str] = None, session: Session = Depends(get_session)):
    return [e.model_dump() for e in BlockedCompanyRepository(session).get_all(search=search)]


@blocked_router.get("/names")
def list_blocked_names(session: Session = Depends(get_session)):
    """All blocked company names (lowercase), for bulk client-side checks."""
    return BlockedCompanyRepository(session).get_names()


@blocked_router.get("/check")
def check_blocked(company: str, session: Session = Depends(get_session)):
    return {"is_blocked": BlockedCompanyRepository(session).is_blocked(company)}


@blocked_router.post("", status_code=201)
def add_blocked(body: BlockedCompanyCreate, session: Session = Depends(get_session)):
    repo = BlockedCompanyRepository(session)
    if repo.is_blocked(body.company_name):
        raise HTTPException(status_code=409, detail="Company already blocked")
    entry = repo.add(company_name=body.company_name, reason=body.reason)
    session.commit()
    session.refresh(entry)
    return entry.model_dump()


@blocked_router.delete("/{id}")
def delete_blocked(id: int, session: Session = Depends(get_session)):
    if BlockedCompanyRepository(session).delete(id):
        session.commit()
    return {"status": "ok"}


@blocked_router.patch("/{id}")
def update_blocked(id: int, body: BlockedCompanyUpdate, session: Session = Depends(get_session)):
    if not BlockedCompanyRepository(session).update(id, body.reason):
        raise HTTPException(status_code=404, detail="Blocked company not found")
    session.commit()
    return {"status": "ok"}


@blocked_router.post("/toggle")
def toggle_blocked(body: BlockedCompanyToggle, session: Session = Depends(get_session)):
    is_blocked, _ = BlockedCompanyRepository(session).toggle(body.company_name)
    session.commit()
    return {"is_blocked": is_blocked}
