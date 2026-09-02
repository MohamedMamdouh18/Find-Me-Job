from datetime import datetime, timedelta

from sqlmodel import Session, select, func

from ..models import FilteredJob, WorkflowRun
from ..models.enums import AiStatus
from ...shared import now

# A run still marked "running" after this long is treated as dead, not in progress.
STALE_RUN_HOURS = 6


class WorkflowRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def start(self, trigger: str = "schedule") -> WorkflowRun:
        """Open a new run, first closing out any earlier run that never reported back."""
        self._fail_stale_runs("superseded by a newer run")
        run = WorkflowRun(trigger=trigger, status="running", started_at=now())
        self.session.add(run)
        return run

    def fail_running(self, reason: str):
        """Public entry point for callers outside a run, e.g. shutdown."""
        self._fail_stale_runs(reason)

    def _fail_stale_runs(self, reason: str):
        stale = self.session.exec(
            select(WorkflowRun).where(WorkflowRun.status == "running")
        ).all()
        for run in stale:
            run.status = "failed"
            run.finished_at = now()
            run.error = run.error or reason
            self.session.add(run)

    def finish(
        self,
        run_id: int,
        status: str = "success",
        error: str | None = None,
        jobs_scraped: int | None = None,
    ) -> WorkflowRun | None:
        run = self.session.get(WorkflowRun, run_id)
        if not run:
            return None

        run.status = status
        run.error = error
        run.finished_at = now()
        if jobs_scraped is not None:
            run.jobs_scraped = jobs_scraped

        # Derive the scoring counts from what actually landed while the run was open,
        # so callers do not have to thread counters through every branch.
        window = (FilteredJob.created_at >= run.started_at) & (
            FilteredJob.created_at <= run.finished_at
        )
        run.jobs_scored = (
            self.session.exec(select(func.count()).select_from(FilteredJob).where(window)).one()
            or 0
        )
        run.jobs_matched = (
            self.session.exec(
                select(func.count())
                .select_from(FilteredJob)
                .where(window)
                .where(FilteredJob.ai_status == AiStatus.FIT.value)
            ).one()
            or 0
        )

        self.session.add(run)
        return run

    def get_recent(self, limit: int = 20) -> list[WorkflowRun]:
        self._expire_stale_runs()
        statement = (
            select(WorkflowRun).order_by(WorkflowRun.started_at.desc()).limit(limit)  # type: ignore[arg-type]
        )
        return list(self.session.exec(statement).all())

    def _expire_stale_runs(self):
        """A run that never called finish would otherwise show as running forever."""
        cutoff = now() - timedelta(hours=STALE_RUN_HOURS)
        stale = self.session.exec(
            select(WorkflowRun)
            .where(WorkflowRun.status == "running")
            .where(WorkflowRun.started_at < cutoff)
        ).all()
        for run in stale:
            run.status = "failed"
            run.finished_at = run.finished_at or now()
            run.error = run.error or f"no completion reported within {STALE_RUN_HOURS}h"
            self.session.add(run)
        if stale:
            self.session.commit()

    def delete_older_than(self, cutoff: datetime):
        from sqlalchemy import delete

        self.session.execute(delete(WorkflowRun).where(WorkflowRun.started_at < cutoff))
