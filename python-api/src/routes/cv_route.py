from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from docx import Document
from sqlmodel import Session

from ..shared import CV_PATH
from ..database import get_session
from ..database.repositories import CVKeywordsRepository

cv_router = APIRouter(prefix="/api/cv", tags=["cv"])


class KeywordsRequest(BaseModel):
    cv_hash: str
    keywords: str


@cv_router.get("")
def get_cv():
    try:
        doc = Document(CV_PATH)
        text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        return {"cv_text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read CV: {str(e)}")


@cv_router.get("/check/{cv_hash}")
def check_cv_hash(cv_hash: str, session: Session = Depends(get_session)):
    repo = CVKeywordsRepository(session)
    return {"exists": repo.hash_exists(cv_hash)}


@cv_router.get("/keywords")
def get_keywords(session: Session = Depends(get_session)):
    repo = CVKeywordsRepository(session)
    row = repo.get_latest()
    if not row:
        return {"keywords": None, "cv_hash": None, "updated_at": None}
    return {"keywords": row.keywords, "cv_hash": row.cv_hash, "updated_at": row.updated_at}


@cv_router.post("/keywords")
def save_keywords(body: KeywordsRequest, session: Session = Depends(get_session)):
    repo = CVKeywordsRepository(session)
    repo.save(body.cv_hash, body.keywords)
    session.commit()
    return {"status": "ok"}
