from datetime import datetime
from sqlmodel import Session, select
from sqlalchemy import delete

from ..models import RunEvent


class RunEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(
        self,
        run_id: int,
        stage: str,
        message: str,
        level: str = "info",
        context: str | None = None,
    ) -> RunEvent:
        event = RunEvent(
            run_id=run_id,
            stage=stage,
            message=message,
            level=level,
            context=context,
        )
        self.session.add(event)
        return event

    def get_by_run_id(self, run_id: int, limit: int | None = None) -> list[RunEvent]:
        """Oldest first. `limit` returns the most recent N, still in ascending order —
        the live endpoint polls this every 2s and only ever renders the last few."""
        if limit is None:
            statement = select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts.asc())  # type: ignore[arg-type]
            return list(self.session.exec(statement).all())

        statement = (
            select(RunEvent)
            .where(RunEvent.run_id == run_id)
            .order_by(RunEvent.ts.desc())  # type: ignore[arg-type]
            .limit(limit)
        )
        return list(reversed(self.session.exec(statement).all()))

    def delete_older_than(self, cutoff: datetime):
        self.session.execute(delete(RunEvent).where(RunEvent.ts < cutoff))
