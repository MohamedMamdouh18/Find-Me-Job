from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from docx import Document
from ..shared import acquire_lock, get_connection, db_lock, CV_PATH

cv_router = APIRouter(prefix="/api/cv", tags=["cv"])


class KeywordsRequest(BaseModel):
    cv_hash: str
    keywords: str


@cv_router.get("")
def get_cv():
    try:
        print(f"Reading CV from {CV_PATH}", flush=True)
        doc = Document(CV_PATH)
        text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        return {"cv_text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read CV: {str(e)}")


@cv_router.get("/check/{cv_hash}")
def check_cv_hash(cv_hash: str):
    acquire_lock()
    conn = get_connection()
    try:
        row = conn.execute("SELECT 1 FROM cv_keywords WHERE cv_hash = ?", (cv_hash,)).fetchone()
        return {"exists": bool(row)}
    finally:
        conn.close()
        db_lock.release()


@cv_router.get("/keywords")
def get_keywords():
    acquire_lock()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT cv_hash, keywords, updated_at FROM cv_keywords ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return {"keywords": None, "cv_hash": None, "updated_at": None}
        return dict(row)
    finally:
        conn.close()
        db_lock.release()


@cv_router.post("/keywords")
def save_keywords(body: KeywordsRequest):
    acquire_lock()
    conn = get_connection()
    try:
        # delete old entry and insert new one to keep only latest
        conn.execute(
            "INSERT OR REPLACE INTO cv_keywords (id, cv_hash, keywords) VALUES (1, ?, ?)",
            (body.cv_hash, body.keywords),
        )
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()
        db_lock.release()
