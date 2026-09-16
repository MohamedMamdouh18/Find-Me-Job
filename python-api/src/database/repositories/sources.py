from sqlmodel import Session, select

from ..models.job_source import JobSource
from ...shared import now


class SourceRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_all(self) -> list[JobSource]:
        return list(self.session.exec(select(JobSource).order_by(JobSource.name)).all())

    def disabled_names(self) -> set[str]:
        """The pipeline asks what to skip, not what to run: a source with no row is
        enabled, so an upgrade changes nothing and a new module needs no migration."""
        rows = self.session.exec(select(JobSource).where(JobSource.enabled.is_(False))).all()
        return {row.name for row in rows}

    def set_enabled(self, name: str, enabled: bool, label: str = "") -> JobSource:
        """Upsert: a source can be switched off before the startup reconcile has
        ever seen it, and the decision has to survive either way. Caller commits."""
        row = self.session.get(JobSource, name)
        if row is None:
            row = JobSource(name=name, label=label or name)
        row.enabled = enabled
        row.updated_at = now()
        self.session.add(row)
        return row

    def reconcile(self, labels: dict[str, str]) -> int:
        """Insert a row for every registered source that has none. Caller commits."""
        existing = {row.name for row in self.session.exec(select(JobSource)).all()}
        added = 0
        for name, label in labels.items():
            if name in existing:
                continue
            self.session.add(JobSource(name=name, label=label))
            added += 1
        return added
