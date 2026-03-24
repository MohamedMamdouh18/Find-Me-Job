from datetime import timedelta
import os

from sqlmodel import Session
from sqlalchemy import create_engine, event
from alembic.config import Config
from alembic import command

from ..shared import now
from .repositories import FilteredJobRepository, PendingJobRepository, SeenJobRepository

DB = os.getenv("DB_PATH", "/data/db/jobs.db")
engine = create_engine(
    f"sqlite:///{DB}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def get_session():
    with Session(engine) as session:
        yield session


def run_migrations():
    ini_path = "alembic.ini"
    alembic_cfg = Config(ini_path)
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{DB}")
    command.upgrade(alembic_cfg, "head")


def delete_old_jobs():
    deletion_old_jobs_days = int(os.getenv("DELETE_OLD_JOBS_DAYS", 60))
    cutoff = now() - timedelta(days=deletion_old_jobs_days)
    with Session(engine) as session:
        PendingJobRepository(session).delete_older_than(cutoff)
        FilteredJobRepository(session).delete_older_than(cutoff)
        SeenJobRepository(session).delete_older_than(cutoff)
        session.commit()
