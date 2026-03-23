from datetime import timedelta
import os

from sqlmodel import Session, SQLModel
from sqlalchemy import create_engine, event

from ..shared import now
from .repositories import PendingJobRepository, SeenJobRepository

DB = "/data/db/jobs.db"
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


def init_db():
    SQLModel.metadata.create_all(engine)

    deletion_old_jobs_days = int(os.getenv("DELETE_OLD_JOBS_DAYS", 60))
    cutoff = now() - timedelta(days=deletion_old_jobs_days)
    with Session(engine) as session:
        PendingJobRepository(session).delete_older_than(cutoff)
        SeenJobRepository(session).delete_older_than(cutoff)
        session.commit()
