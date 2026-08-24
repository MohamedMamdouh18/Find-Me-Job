from datetime import timedelta
import os

from sqlmodel import Session, SQLModel
from sqlalchemy import create_engine, event, inspect
from alembic.config import Config
from alembic import command

from ..shared import now
from .repositories import (
    FilteredJobRepository,
    PendingJobRepository,
    SeenJobRepository,
    WorkflowRunRepository,
)

DB = os.getenv("DB_PATH") or "/data/db/jobs.db"
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
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{DB}")

    # The first revision in the chain ALTERs tables that an earlier create_all() used
    # to make, so it cannot build a database from nothing. On a brand new file, create
    # the schema straight from the models and stamp it as current instead.
    if _is_empty_database():
        from . import models  # noqa: F401  (registers every table on SQLModel.metadata)

        SQLModel.metadata.create_all(engine)
        command.stamp(alembic_cfg, "head")
        print("Initialised a new database from the current models.", flush=True)
        return

    command.upgrade(alembic_cfg, "head")


def _is_empty_database() -> bool:
    """True for a database with no tables at all — a genuinely fresh install."""
    return not inspect(engine).get_table_names()


def delete_old_jobs():
    deletion_old_jobs_days = int(os.getenv("DELETE_OLD_JOBS_DAYS") or 60)
    cutoff = now() - timedelta(days=deletion_old_jobs_days)
    with Session(engine) as session:
        PendingJobRepository(session).delete_older_than(cutoff)
        FilteredJobRepository(session).delete_older_than(cutoff)
        SeenJobRepository(session).delete_older_than(cutoff)
        WorkflowRunRepository(session).delete_older_than(cutoff)
        session.commit()
