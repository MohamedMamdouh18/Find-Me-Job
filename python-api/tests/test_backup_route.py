"""GET /api/backup resource handling.

sqlite3's context manager commits or rolls back; it does NOT close the connection,
so a plain `with sqlite3.connect(...)` leaks a file descriptor per request.
"""

import glob
import os
import sqlite3
import tempfile

from fastapi.testclient import TestClient

from src.main import app
from src.routes import backup_route


def _seed_db(path: str):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (a INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()


class _TrackingConnection:
    """Proxies a real connection and records whether close() was ever called.

    Probing with `conn.execute(...)` from the test thread cannot answer this: a live
    connection raises ProgrammingError across threads exactly as a closed one does.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.closed = False

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)

    def close(self):
        self.closed = True
        self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_backup_closes_its_connection(tmp_path, monkeypatch):
    db_path = str(tmp_path / "jobs.db")
    _seed_db(db_path)
    monkeypatch.setattr(backup_route, "DB", db_path)

    opened: list[_TrackingConnection] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = _TrackingConnection(real_connect(*args, **kwargs))
        opened.append(conn)
        return conn

    monkeypatch.setattr(backup_route.sqlite3, "connect", tracking_connect)

    client = TestClient(app)
    res = client.get("/api/backup")
    assert res.status_code == 200
    assert opened, "route did not open a connection"
    assert all(c.closed for c in opened), (
        "backup connection was never closed: sqlite3's context manager commits or "
        "rolls back, it does not close"
    )


def test_backup_cleans_temp_dir_when_vacuum_fails(tmp_path, monkeypatch):
    """The cleanup background task never runs when VACUUM INTO raises."""
    db_path = str(tmp_path / "missing.db")
    monkeypatch.setattr(backup_route, "DB", db_path)

    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "fmj-backup-*")))

    client = TestClient(app)
    res = client.get("/api/backup")
    assert res.status_code == 500

    leaked = set(glob.glob(os.path.join(tempfile.gettempdir(), "fmj-backup-*"))) - before
    assert not leaked, f"temp dir orphaned on failure: {sorted(leaked)}"
