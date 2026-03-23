from fastapi import APIRouter
from ..shared import get_connection, acquire_lock, db_lock

db_router = APIRouter(prefix="/api/db", tags=["db"])


@db_router.post("/init")
def init_db():
    acquire_lock()
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS seen_jobs (
                id TEXT PRIMARY KEY,
                seen_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pending_jobs (
                id TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                location TEXT,
                applylink TEXT,
                description TEXT,
                website TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS cv_keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cv_hash TEXT NOT NULL,
                keywords TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # clean records older than 2 months
        conn.execute("""
            DELETE FROM seen_jobs
            WHERE seen_at < datetime('now', '-2 months')
        """)
        conn.execute("""
            DELETE FROM pending_jobs
            WHERE created_at < datetime('now', '-2 months')
        """)

        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()
        db_lock.release()
