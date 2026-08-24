from datetime import datetime
from sqlmodel import SQLModel, Session, create_engine, select
from src.database.models import FilteredJob, JobStatusHistory
from src.database.models.enums import AiStatus, UserStatus
from src.database.repositories.filtered_jobs import FilteredJobRepository


def test_readd_existing_preserves_created_at_and_status():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        repo = FilteredJobRepository(session)

        original_created_at = datetime(2026, 1, 1, 12, 0, 0)
        job1 = FilteredJob(
            id="job_123",
            title="Backend Engineer",
            company="Acme Corp",
            location="Remote",
            applylink="https://example.com/apply",
            description="Build APIs",
            website="LinkedIn",
            score=75,
            application_document="Cover letter 1",
            ai_status=AiStatus.FIT,
            user_status=UserStatus.NEW,
            created_at=original_created_at,
        )
        repo.add(job1)
        session.commit()

        # Check initial state
        saved1 = session.get(FilteredJob, "job_123")
        assert saved1 is not None
        assert saved1.score == 75
        assert saved1.user_status == UserStatus.NEW
        assert saved1.created_at == original_created_at

        # Check history has 1 row
        histories = session.exec(
            select(JobStatusHistory).where(JobStatusHistory.job_id == "job_123")
        ).all()
        assert len(histories) == 1
        assert histories[0].status == "new"

        # Re-add the same job with a new score, new created_at, and default user_status (new)
        job2 = FilteredJob(
            id="job_123",
            title="Backend Engineer",
            company="Acme Corp",
            location="Remote",
            applylink="https://example.com/apply",
            description="Build APIs updated",
            website="LinkedIn",
            score=92,
            application_document="Cover letter updated",
            ai_status=AiStatus.FIT,
            user_status=UserStatus.NEW,
            created_at=datetime(2026, 2, 1, 12, 0, 0),
        )
        repo.add(job2)
        session.commit()

        # Verify created_at and user_status preserved, score updated
        saved2 = session.get(FilteredJob, "job_123")
        assert saved2 is not None
        assert saved2.score == 92
        assert saved2.user_status == UserStatus.NEW
        assert saved2.created_at == original_created_at

        # Verify no duplicate history row was added
        histories2 = session.exec(
            select(JobStatusHistory).where(JobStatusHistory.job_id == "job_123")
        ).all()
        assert len(histories2) == 1


def test_readd_does_not_revert_a_status_the_user_set():
    """The re-add above sends the same status it started with, so it cannot tell a
    preserved status from an overwritten one. This is the case that can: the user
    marks the job applied, then the workflow re-scores it and POSTs `new` again."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    def job(score: int, created: datetime) -> FilteredJob:
        return FilteredJob(
            id="job_456",
            title="Backend Engineer",
            company="Acme Corp",
            location="Remote",
            applylink="https://example.com/apply",
            description="Build APIs",
            website="LinkedIn",
            score=score,
            ai_status=AiStatus.FIT,
            user_status=UserStatus.NEW,
            created_at=created,
        )

    with Session(engine) as session:
        repo = FilteredJobRepository(session)
        repo.add(job(70, datetime(2026, 1, 1, 12, 0, 0)))
        session.commit()
        repo.update_status("job_456", UserStatus.APPLIED)
        session.commit()

        repo.add(job(92, datetime(2026, 6, 1, 12, 0, 0)))
        session.commit()

        saved = session.get(FilteredJob, "job_456")
        assert saved is not None
        assert saved.score == 92
        assert saved.user_status == UserStatus.APPLIED
        assert saved.created_at == datetime(2026, 1, 1, 12, 0, 0)

        # A re-add is not a transition, so it must not appear in the timeline
        statuses = [
            h.status
            for h in session.exec(
                select(JobStatusHistory).where(JobStatusHistory.job_id == "job_456")
            ).all()
        ]
        assert statuses == ["new", "applied"]
