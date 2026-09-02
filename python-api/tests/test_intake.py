from sqlmodel import SQLModel, Session, create_engine, select
from sqlmodel.pool import StaticPool

import src.database.models  # noqa: F401
from src.database.models import BlockedCompany, PendingJob, SeenJob
from src.database.repositories import BlockedCompanyRepository
from src.schemas.jobs import PendingJobRequest
from src.services.intake import save_pending_job


def test_save_pending_job_blocked_company():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        BlockedCompanyRepository(session).add("BadCorp", reason="Spam")
        session.commit()

        job = PendingJobRequest(
            id="job_blocked_1",
            title="Engineer",
            company="BadCorp",
            location="Remote",
            applylink="https://example.com/1",
            description="Nice job",
            website="LinkedIn",
        )
        res = save_pending_job(session, job)
        assert res == "blocked"

        # Check job is in seen_jobs
        seen = session.exec(select(SeenJob).where(SeenJob.id == "job_blocked_1")).first()
        assert seen is not None

        # Check job is NOT in pending_jobs
        pending = session.exec(select(PendingJob).where(PendingJob.id == "job_blocked_1")).first()
        assert pending is None


def test_save_pending_job_queued_and_deduplicated():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        job = PendingJobRequest(
            id="job_good_1",
            title="Python Dev",
            company="GoodCorp",
            location="Remote",
            applylink="https://example.com/2",
            description="Write python",
            website="RemoteOK",
        )
        res1 = save_pending_job(session, job)
        assert res1 == "queued"

        # Check in pending and seen
        assert session.exec(select(PendingJob).where(PendingJob.id == "job_good_1")).first() is not None
        assert session.exec(select(SeenJob).where(SeenJob.id == "job_good_1")).first() is not None

        # Second intake should return already_seen
        res2 = save_pending_job(session, job)
        assert res2 == "already_seen"
