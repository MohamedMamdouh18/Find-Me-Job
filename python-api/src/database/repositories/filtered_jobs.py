from datetime import datetime, timedelta

from sqlalchemy import case, or_
from sqlmodel import Session, select, func

from ..models import FilteredJob, JobStatusHistory
from ..models.enums import AiStatus, UserStatus, APPLIED_BUCKET
from ..models.starred_company import StarredCompany
from ...shared import now

SORTABLE_COLUMNS = {
    "updated_at": FilteredJob.updated_at,
    "created_at": FilteredJob.created_at,
    "score": FilteredJob.score,
    "title": FilteredJob.title,
    "company": FilteredJob.company,
    "website": FilteredJob.website,
}

APPLIED_VALUES = [s.value for s in APPLIED_BUCKET]


class FilteredJobRepository:
    def __init__(self, session: Session):
        self.session = session

    def exists(self, job_id: str) -> bool:
        return self.session.get(FilteredJob, job_id) is not None

    def add(self, job: FilteredJob):
        self.session.merge(job)

    def get(self, job_id: str) -> FilteredJob | None:
        return self.session.get(FilteredJob, job_id)

    def update_status(self, job_id: str, user_status: UserStatus) -> bool:
        job = self.session.get(FilteredJob, job_id)
        if not job:
            return False
        if job.user_status == user_status:
            return True  # idempotent — no history entry for no-op
        job.user_status = user_status
        job.updated_at = now()
        self.session.add(job)
        self.session.add(JobStatusHistory(job_id=job_id, status=user_status.value))
        return True

    def delete(self, job_id: str) -> bool:
        job = self.session.get(FilteredJob, job_id)
        if not job:
            return False
        self.session.delete(job)
        return True

    def delete_older_than(self, cutoff: datetime):
        statement = select(FilteredJob).where(FilteredJob.updated_at < cutoff)
        for job in self.session.exec(statement).all():
            self.session.delete(job)

    def get_stats(self) -> dict:
        ai_status_col = FilteredJob.__table__.c.ai_status  # type: ignore[attr-defined]
        user_status_col = FilteredJob.__table__.c.user_status  # type: ignore[attr-defined]

        ai_counts = [
            func.sum(case((ai_status_col == s.value, 1), else_=0)).label(s.value)
            for s in AiStatus
        ]
        user_counts = [
            func.sum(case((user_status_col == s.value, 1), else_=0)).label(s.value)
            for s in UserStatus
        ]

        stats = self.session.exec(
            select(  # type: ignore[call-overload]
                func.count().label("total"),
                *ai_counts,
                *user_counts,
                func.avg(FilteredJob.score).label("avg_score"),
            )
        ).one()

        result = {"total": stats.total or 0, "avg_score": round(stats.avg_score) if stats.avg_score else 0}
        for s in AiStatus:
            result[s.value] = getattr(stats, s.value) or 0
        for s in UserStatus:
            result[s.value] = getattr(stats, s.value) or 0
        return result

    def get_all_scores(self) -> list[int]:
        statement = select(FilteredJob.score).order_by(FilteredJob.score.asc())  # type: ignore[arg-type]
        return list(self.session.exec(statement).all())

    def get_daily_applied(self, days: int = 7) -> list[dict]:
        today = now().date()
        cutoff = today - timedelta(days=days - 1)
        updated_at_col = FilteredJob.__table__.c.updated_at  # type: ignore[attr-defined]
        user_status_col = FilteredJob.__table__.c.user_status  # type: ignore[attr-defined]

        day_label = func.substr(updated_at_col, 1, 10).label("day")

        statement = (
            select(  # type: ignore[call-overload]
                day_label,
                func.count().label("applied"),
            )
            .where(updated_at_col >= str(cutoff))
            .where(user_status_col.in_(APPLIED_VALUES))
            .group_by(day_label)
            .order_by(day_label.asc())
        )
        rows = self.session.exec(statement).all()
        db_data = {r.day: r.applied for r in rows}

        result = []
        for i in range(days):
            d = cutoff + timedelta(days=i)
            key = d.strftime("%Y-%m-%d")
            result.append({"day": key, "applied": db_data.get(key, 0)})
        return result

    def get_stats_by_source(self) -> list[dict]:
        website_col = FilteredJob.__table__.c.website  # type: ignore[attr-defined]
        user_status_col = FilteredJob.__table__.c.user_status  # type: ignore[attr-defined]

        statement = (
            select(  # type: ignore[call-overload]
                website_col.label("source"),
                func.count().label("total"),
                func.sum(
                    case(
                        (user_status_col.in_(APPLIED_VALUES), 1),
                        else_=0,
                    )
                ).label("applied"),
            )
            .group_by(website_col)
            .order_by(func.count().desc())
        )
        rows = self.session.exec(statement).all()
        return [
            {
                "source": r.source or "Unknown",
                "total": r.total,
                "applied": r.applied or 0,
            }
            for r in rows
        ]

    def get_status_history(self, job_id: str) -> list[dict]:
        statement = (
            select(JobStatusHistory)
            .where(JobStatusHistory.job_id == job_id)
            .order_by(JobStatusHistory.changed_at.asc())  # type: ignore[arg-type]
        )
        rows = self.session.exec(statement).all()
        return [{"status": r.status, "changed_at": r.changed_at.isoformat()} for r in rows]

    def get_distinct_values(self, column: str) -> list[str]:
        col_map = {
            "company": FilteredJob.company,
            "website": FilteredJob.website,
            "location": FilteredJob.location,
        }
        col = col_map.get(column)
        if not col:
            return []
        statement = select(col).distinct().order_by(col.asc())  # type: ignore[arg-type]
        return list(self.session.exec(statement).all())

    def get_all(
        self,
        ai_status: AiStatus | None = None,
        user_status: UserStatus | None = None,
        easy_apply: bool | None = None,
        min_score: int | None = None,
        search: str | None = None,
        company: str | None = None,
        website: str | None = None,
        location: str | None = None,
        starred_only: bool = False,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[FilteredJob], int]:
        statement = select(FilteredJob)

        if ai_status:
            statement = statement.where(FilteredJob.ai_status == ai_status.value)
        if user_status:
            statement = statement.where(FilteredJob.user_status == user_status.value)
        if easy_apply is not None:
            statement = statement.where(FilteredJob.easy_apply == easy_apply)
        if min_score is not None:
            statement = statement.where(FilteredJob.score >= min_score)
        if search:
            pattern = f"%{search}%"
            statement = statement.where(
                or_(
                    FilteredJob.title.ilike(pattern),  # type: ignore[union-attr]
                    FilteredJob.company.ilike(pattern),  # type: ignore[union-attr]
                    FilteredJob.location.ilike(pattern),  # type: ignore[union-attr]
                )
            )
        if company:
            statement = statement.where(FilteredJob.company == company)
        if website:
            statement = statement.where(FilteredJob.website == website)
        if location:
            statement = statement.where(FilteredJob.location == location)
        if starred_only:
            starred_names_subq = select(StarredCompany.company_name)
            statement = statement.where(
                func.lower(FilteredJob.company).in_(starred_names_subq)  # type: ignore[arg-type]
            )

        count_statement = select(func.count()).select_from(statement.subquery())
        total = self.session.exec(count_statement).one()

        sort_col = SORTABLE_COLUMNS.get(sort_by, FilteredJob.updated_at)
        statement = statement.order_by(
            sort_col.desc() if sort_order == "desc" else sort_col.asc()  # type: ignore
        )

        statement = statement.offset((page - 1) * page_size).limit(page_size)

        return list(self.session.exec(statement).all()), total
