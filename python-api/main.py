import sqlite3
import threading
import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Optional
from docx import Document
import os


class TimedLock:
    """Lock that auto-releases if held longer than max_hold_seconds."""

    def __init__(self, max_hold_seconds=5):
        self._lock = threading.Lock()
        self._max_hold = max_hold_seconds
        self._acquired_at = None
        self._timer = None

    def acquire(self, timeout=5):
        acquired = self._lock.acquire(timeout=timeout)
        if not acquired:
            return False
        self._acquired_at = time.time()
        self._timer = threading.Timer(self._max_hold, self._force_release)
        self._timer.start()
        return True

    def release(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if self._lock.locked():
            self._lock.release()

    def _force_release(self):
        if self._lock.locked():
            self._lock.release()

    def locked(self):
        return self._lock.locked()


db_lock = TimedLock(max_hold_seconds=5)
app = FastAPI()
DB = "/data/db/jobs.db"
CV_PATH = "/data/cv.docx"
PARAMS_DIR = "/data/params"


def get_db():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def acquire_lock(timeout=5):
    acquired = db_lock._lock.acquire(timeout=timeout)
    if not acquired:
        raise HTTPException(status_code=503, detail="DB lock timeout — try again")


# ── Database ──────────────────────────────────────────


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


@app.post("/query")
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


@app.post("/db/init")
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


@app.get("/job/exists")
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


@app.post("/job/pending")
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


@app.post("/job/complete")
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


# ── CV ────────────────────────────────────────────────


@app.get("/cv")
def get_cv():
    doc = Document(CV_PATH)
    text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    return {"cv": text}


# ── Prompts ───────────────────────────────────────────


@app.get("/param/{name}")
def get_param(name: str):
    path = os.path.join(PARAMS_DIR, f"{name}.txt")
    if not os.path.exists(path):
        return {"error": f"param '{name}' not found"}
    with open(path, "r") as f:
        return {"param": f.read()}


# ── Health ────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok"}
