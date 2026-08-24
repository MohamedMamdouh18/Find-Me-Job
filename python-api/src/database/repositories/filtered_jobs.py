from datetime import datetime, timedelta

from sqlalchemy import case, delete, or_
from sqlalchemy.orm import load_only
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

# Columns the jobs table needs; the two large text blobs are fetched on demand.
LIST_COLUMNS = [
    FilteredJob.id,
    FilteredJob.title,
    FilteredJob.company,
    FilteredJob.location,
    FilteredJob.applylink,
    FilteredJob.website,
    FilteredJob.score,
    FilteredJob.easy_apply,
    FilteredJob.ai_status,
    FilteredJob.user_status,
    FilteredJob.created_at,
    FilteredJob.updated_at,
]

SCORE_BIN_SIZE = 10


class FilteredJobRepository:
    def __init__(self, session: Session):
        self.session = session

    def exists(self, job_id: str) -> bool:
        return self.session.get(FilteredJob, job_id) is not None

    def add(self, job: FilteredJob):
        existing = self.session.get(FilteredJob, job.id)
        if existing:
            # merge() copies every column off the new model, so without this a re-score
            # backdates created_at to now and reverts a status the user set by hand.
            # Preserving the status also means a re-add can never be a transition, so
            # it must not write a history row — status changes go through update_status.
            job.created_at = existing.created_at
            job.user_status = existing.user_status
        else:
            # Record the initial status in the history log
            self.session.add(JobStatusHistory(job_id=job.id, status=job.user_status.value))

        # Insert or update the main job record
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
        self.session.execute(delete(JobStatusHistory).where(JobStatusHistory.job_id == job_id))
        self.session.delete(job)
        return True

    def delete_all(self) -> int:
        """Wipe the table. History goes first — it has no FK cascade."""
        total = self.session.exec(select(func.count()).select_from(FilteredJob)).one()
        self.session.execute(delete(JobStatusHistory))
        self.session.execute(delete(FilteredJob))
        return int(total)

    def delete_older_than(self, cutoff: datetime):
        stale_ids = select(FilteredJob.id).where(FilteredJob.updated_at < cutoff)
        self.session.execute(
            delete(JobStatusHistory).where(JobStatusHistory.job_id.in_(stale_ids))  # type: ignore[attr-defined]
        )
        self.session.execute(delete(FilteredJob).where(FilteredJob.updated_at < cutoff))

    def get_stats(self) -> dict:
        ai_status_col = FilteredJob.__table__.c.ai_status  # type: ignore[attr-defined]
        user_status_col = FilteredJob.__table__.c.user_status  # type: ignore[attr-defined]

        ai_counts = [
            func.sum(case((ai_status_col == s.value, 1), else_=0)).label(s.value) for s in AiStatus
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
                func.sum(case((FilteredJob.easy_apply == True, 1), else_=0)).label("easy_apply"),  # noqa: E712
            )
        ).one()

        result = {
            "total": stats.total or 0,
            "avg_score": round(stats.avg_score) if stats.avg_score else 0,
            "easy_apply": stats.easy_apply or 0,
        }
        for s in AiStatus:
            result[s.value] = getattr(stats, s.value) or 0
        for s in UserStatus:
            result[s.value] = getattr(stats, s.value) or 0
        result["median_score"] = self._median_score(result["total"])
        return result

    def _median_score(self, total: int) -> int:
        """The average is pulled around by the zeros the experience gate produces;
        the median is what "a typical match" actually looks like."""
        if not total:
            return 0
        return int(
            self.session.exec(
                select(FilteredJob.score)  # type: ignore[call-overload]
                .order_by(FilteredJob.score.asc())  # type: ignore[attr-defined]
                .offset((total - 1) // 2)
                .limit(1)
            ).one()
        )

    def get_score_distribution(self) -> list[dict]:
        """Bin scores server-side so the dashboard never downloads one row per job."""
        score_col = FilteredJob.__table__.c.score  # type: ignore[attr-defined]
        # Floor division, not `/` — SQLAlchemy renders `/` as true division, which
        # would produce fractional bin starts that match no bucket.
        # Scores are 0-100; 100 folds into the top bin so it is never dropped.
        bin_start = (
            func.min(score_col // SCORE_BIN_SIZE, (100 // SCORE_BIN_SIZE) - 1) * SCORE_BIN_SIZE
        ).label("bin_start")

        rows = self.session.exec(
            select(bin_start, func.count().label("count")).group_by(bin_start)  # type: ignore[call-overload]
        ).all()
        counts = {int(r.bin_start): r.count for r in rows}

        return [
            {"start": start, "end": start + SCORE_BIN_SIZE - 1, "count": counts.get(start, 0)}
            for start in range(0, 100, SCORE_BIN_SIZE)
        ]

    def get_daily_applied(self, days: int = 7) -> list[dict]:
        """Applications per day, read from the status log rather than from the
        row's current status: a job that moved on to Interview was still applied
        to on the day it was applied to, and the row no longer says so."""
        today = now().date()
        cutoff = today - timedelta(days=days - 1)
        changed_at_col = JobStatusHistory.__table__.c.changed_at  # type: ignore[attr-defined]
        status_col = JobStatusHistory.__table__.c.status  # type: ignore[attr-defined]

        day_label = func.substr(changed_at_col, 1, 10).label("day")

        statement = (
            select(  # type: ignore[call-overload]
                day_label,
                func.count(func.distinct(JobStatusHistory.job_id)).label("applied"),
            )
            .where(changed_at_col >= str(cutoff))
            .where(status_col.in_(APPLIED_VALUES))
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

    def _ever_reached(self, statuses: list[str]) -> int:
        """Jobs that passed through a stage at any point. A funnel counts arrivals,
        so reading the current status would make later stages shrink the earlier ones."""
        status_col = JobStatusHistory.__table__.c.status  # type: ignore[attr-defined]
        return int(
            self.session.exec(
                select(func.count(func.distinct(JobStatusHistory.job_id)))  # type: ignore[call-overload]
                .where(status_col.in_(statuses))
            ).one()
        )

    def get_funnel(self) -> dict:
        ai_status_col = FilteredJob.__table__.c.ai_status  # type: ignore[attr-defined]
        matched = int(
            self.session.exec(
                select(func.count()).select_from(FilteredJob)  # type: ignore[call-overload]
                .where(ai_status_col == AiStatus.FIT.value)
            ).one()
        )
        return {
            "matched": matched,
            "applied": self._ever_reached(APPLIED_VALUES),
            "interviewing": self._ever_reached(
                [UserStatus.ASSESSMENT.value, UserStatus.INTERVIEW.value]
            ),
            "offers": self._ever_reached([UserStatus.OFFER.value]),
            "events": self._ever_reached(
                APPLIED_VALUES
                + [
                    UserStatus.ASSESSMENT.value,
                    UserStatus.INTERVIEW.value,
                    UserStatus.OFFER.value,
                    UserStatus.REJECTED.value,
                ]
            ),
        }

    def get_descriptions(self, job_ids: list[str]) -> dict[str, str]:
        """Only the blob, only for the rows on screen — the list query deliberately
        leaves it out."""
        if not job_ids:
            return {}
        rows = self.session.exec(
            select(FilteredJob.id, FilteredJob.description).where(  # type: ignore[call-overload]
                FilteredJob.id.in_(job_ids)  # type: ignore[attr-defined]
            )
        ).all()
        return {r.id: r.description or "" for r in rows}

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

    def _build_filters(
        self,
        ai_status: AiStatus | None,
        user_status: UserStatus | None,
        easy_apply: bool | None,
        min_score: int | None,
        max_score: int | None,
        search: str | None,
        company: str | None,
        website: str | None,
        location: str | None,
        starred_only: bool,
    ) -> list:
        conditions = []
        if ai_status:
            conditions.append(FilteredJob.ai_status == ai_status.value)
        if user_status:
            conditions.append(FilteredJob.user_status == user_status.value)
        if easy_apply is not None:
            conditions.append(FilteredJob.easy_apply == easy_apply)
        if min_score is not None:
            conditions.append(FilteredJob.score >= min_score)
        if max_score is not None:
            conditions.append(FilteredJob.score <= max_score)
        if search:
            pattern = f"%{search}%"
            conditions.append(
                or_(
                    FilteredJob.title.ilike(pattern),  # type: ignore[union-attr]
                    FilteredJob.company.ilike(pattern),  # type: ignore[union-attr]
                    FilteredJob.location.ilike(pattern),  # type: ignore[union-attr]
                )
            )
        if company:
            conditions.append(FilteredJob.company == company)
        if website:
            conditions.append(FilteredJob.website == website)
        if location:
            conditions.append(FilteredJob.location == location)
        if starred_only:
            conditions.append(
                func.lower(FilteredJob.company).in_(select(StarredCompany.company_name))  # type: ignore[arg-type]
            )
        return conditions

    def get_all(
        self,
        ai_status: AiStatus | None = None,
        user_status: UserStatus | None = None,
        easy_apply: bool | None = None,
        min_score: int | None = None,
        max_score: int | None = None,
        search: str | None = None,
        company: str | None = None,
        website: str | None = None,
        location: str | None = None,
        starred_only: bool = False,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20,
        include_body: bool = True,
    ) -> tuple[list[FilteredJob], int]:
        conditions = self._build_filters(
            ai_status,
            user_status,
            easy_apply,
            min_score,
            max_score,
            search,
            company,
            website,
            location,
            starred_only,
        )

        # Count straight off the table — wrapping the row query in a subquery would
        # make SQLite materialise every column, including the description blob.
        count_statement = select(func.count()).select_from(FilteredJob)
        for condition in conditions:
            count_statement = count_statement.where(condition)
        total = self.session.exec(count_statement).one()

        statement = select(FilteredJob)
        for condition in conditions:
            statement = statement.where(condition)

        if not include_body:
            statement = statement.options(load_only(*LIST_COLUMNS))  # type: ignore[arg-type]

        sort_col = SORTABLE_COLUMNS.get(sort_by, FilteredJob.updated_at)
        statement = statement.order_by(
            sort_col.desc() if sort_order == "desc" else sort_col.asc()  # type: ignore
        )
        statement = statement.offset((page - 1) * page_size).limit(page_size)

        return list(self.session.exec(statement).all()), total

    def get_top_companies(self, limit: int = 20) -> list[dict]:
        """Ranked by best score, then volume: at one job per company a frequency
        ranking has nothing to rank, but the best score always separates them."""
        company_col = FilteredJob.__table__.c.company  # type: ignore[attr-defined]

        statement = (
            select(  # type: ignore[call-overload]
                company_col.label("company"),
                func.count().label("job_count"),
                func.max(FilteredJob.score).label("best_score"),
                func.max(FilteredJob.created_at).label("last_seen"),
            )
            .group_by(company_col)
            .order_by(func.max(FilteredJob.score).desc(), func.count().desc())
            .limit(limit)
        )
        rows = self.session.exec(statement).all()
        return [
            {
                "company": r.company,
                "job_count": r.job_count,
                "best_score": r.best_score or 0,
                "last_seen": str(r.last_seen) if r.last_seen else None,
            }
            for r in rows
        ]
