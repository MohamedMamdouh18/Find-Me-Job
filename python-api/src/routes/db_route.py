from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..shared import acquire_lock, db_lock, get_db

db_router = APIRouter(prefix="/api/db", tags=["api", "db"])


class QueryRequest(BaseModel):
    sql: str
    params: list[Any] = []


class PendingJobRequest(BaseModel):
    id: str
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    applylink: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None


@db_router.post("/query")
def query(req: QueryRequest):
    acquire_lock()
    try:
        con = get_db()
        cur = con.cursor()
        statements = [s.strip() for s in req.sql.split(";") if s.strip()]
        for i, statement in enumerate(statements):
            if i == len(statements) - 1:
                cur.execute(statement, req.params)
            else:
                cur.execute(statement)
        con.commit()
        rows = cur.fetchall()
        con.close()
    finally:
        db_lock.release()
    return {"rows": [dict(r) for r in rows]}


@db_router.post("/init")
def init_db():
    acquire_lock()
    try:
        con = get_db()
        cur = con.cursor()
        statements = [
            "CREATE TABLE IF NOT EXISTS seen_jobs (id TEXT PRIMARY KEY, seen_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE IF NOT EXISTS cv_keywords (id INTEGER PRIMARY KEY, cv_hash TEXT NOT NULL, keywords TEXT NOT NULL, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE IF NOT EXISTS pending_jobs (id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT, applylink TEXT, description TEXT, website TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
            "DELETE FROM seen_jobs WHERE seen_at < datetime('now', '-2 months')",
            "DELETE FROM pending_jobs WHERE created_at < datetime('now', '-2 months')",
        ]
        for s in statements:
            cur.execute(s)
        con.commit()
        con.close()
    finally:
        db_lock.release()
    return {"status": "ok"}


@db_router.get("/job/exists")
def job_exists(jobid: str):
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "SELECT 1 FROM seen_jobs WHERE id = ? UNION SELECT 1 FROM pending_jobs WHERE id = ?",
        (jobid, jobid),
    )
    exists = cur.fetchone() is not None
    con.close()
    return {"exists": exists}


@db_router.post("/job/pending")
def add_pending_job(job: PendingJobRequest):
    acquire_lock()
    try:
        con = get_db()
        cur = con.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO pending_jobs (id, title, company, location, applylink, description, website) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                job.id,
                job.title,
                job.company,
                job.location,
                job.applylink,
                job.description,
                job.website,
            ),
        )
        con.commit()
        inserted = cur.rowcount > 0
        con.close()
    finally:
        db_lock.release()
    return {"inserted": inserted}


@db_router.post("/job/complete")
def complete_job(jobid: str):
    acquire_lock()
    try:
        con = get_db()
        cur = con.cursor()
        cur.execute("SELECT id FROM pending_jobs WHERE id = ?", (jobid,))
        if cur.fetchone() is None:
            con.close()
            raise HTTPException(status_code=404, detail=f"Job {jobid} not found in pending_jobs")
        cur.execute("INSERT OR IGNORE INTO seen_jobs (id) VALUES (?)", (jobid,))
        cur.execute("DELETE FROM pending_jobs WHERE id = ?", (jobid,))
        con.commit()
        con.close()
    finally:
        db_lock.release()
    return {"status": "ok", "jobid": jobid}
