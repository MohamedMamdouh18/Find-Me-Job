from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..shared import acquire_lock, get_connection, db_lock

jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class PendingJobRequest(BaseModel):
    id: str
    title: str
    company: str
    location: str
    applylink: str
    description: str
    website: str


@jobs_router.get("/exists")
def job_exists(jobid: str):
    acquire_lock()
    con = get_connection()
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT 1 FROM seen_jobs WHERE id = ? UNION SELECT 1 FROM pending_jobs WHERE id = ?",
            (jobid, jobid),
        )
        exists = cur.fetchone() is not None
        return {"exists": exists}
    finally:
        con.close()
        db_lock.release()


@jobs_router.post("/pending")
def add_pending_job(job: PendingJobRequest):
    acquire_lock()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO pending_jobs
                (id, title, company, location, applylink, description, website)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
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
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()
        db_lock.release()


@jobs_router.post("/job/complete")
def complete_job(jobid: str):
    acquire_lock()
    con = get_connection()
    try:
        cur = con.cursor()
        cur.execute("SELECT id FROM pending_jobs WHERE id = ?", (jobid,))
        if cur.fetchone() is None:
            con.close()
            raise HTTPException(status_code=404, detail=f"Job {jobid} not found in pending_jobs")
        cur.execute("INSERT OR IGNORE INTO seen_jobs (id) VALUES (?)", (jobid,))
        cur.execute("DELETE FROM pending_jobs WHERE id = ?", (jobid,))
        con.commit()
    finally:
        con.close()
        db_lock.release()
    return {"status": "ok", "jobid": jobid}


@jobs_router.get("/pending")
def get_pending_jobs():
    acquire_lock()
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM pending_jobs ORDER BY created_at DESC").fetchall()
        return {"rows": [dict(r) for r in rows]}
    finally:
        conn.close()
        db_lock.release()
