import sqlite3
import threading
import time

from fastapi import HTTPException


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
    acquired = db_lock.acquire(timeout=timeout)
    if not acquired:
        raise HTTPException(status_code=503, detail="DB lock timeout - try again")
