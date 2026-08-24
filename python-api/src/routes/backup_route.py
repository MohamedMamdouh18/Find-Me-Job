import os
import sqlite3
import tempfile

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from ..database.core import DB
from ..shared import now

backup_router = APIRouter(prefix="/api/backup", tags=["backup"])


@backup_router.get("")
def download_backup(background_tasks: BackgroundTasks):
    """Consistent snapshot of jobs.db.

    Uses VACUUM INTO rather than copying the file: with WAL enabled a raw copy can
    capture a torn database whose committed pages still live in the -wal sidecar.
    """
    tmp_dir = tempfile.mkdtemp(prefix="fmj-backup-")
    target = os.path.join(tmp_dir, "jobs.db")

    try:
        with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:
            conn.execute("VACUUM INTO ?", (target,))
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"Backup failed: {e}")

    background_tasks.add_task(_cleanup, tmp_dir, target)

    stamp = now().strftime("%Y%m%d-%H%M%S")
    return FileResponse(
        target,
        media_type="application/octet-stream",
        filename=f"jobs-backup-{stamp}.db",
    )


def _cleanup(tmp_dir: str, target: str):
    for path in (target, tmp_dir):
        try:
            os.rmdir(path) if os.path.isdir(path) else os.remove(path)
        except OSError:
            pass
