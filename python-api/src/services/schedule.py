"""Builds the scheduler's jobs from settings, and applies changes without a restart.

The jobstore is in-memory, so app_settings is the only durable schedule state:
the lifespan rebuilds both jobs from it at boot, and every write re-applies here.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, time

from apscheduler.triggers.cron import CronTrigger

from . import settings
from .pipeline import release_run_lock, run_pipeline, try_acquire_lock_for_retention
from ..database.core import delete_old_jobs
from ..database.models.enums import PipelineMode, RunTrigger
from ..shared import TIMEZONE, scheduler

logger = logging.getLogger(__name__)

PIPELINE_JOB_ID = "pipeline"
RETENTION_JOB_ID = "retention"

# APScheduler defaults this to 1 second, so a container booting at 01:05 after a
# 01:00 fire drops that run entirely — a whole day missed in daily mode. An hour
# of grace plus coalesce=True runs the missed job exactly once on startup.
MISFIRE_GRACE_SECONDS = 3600


def pipeline_trigger() -> CronTrigger:
    """Both modes compile to one CronTrigger; the user never sees a cron expression.

    Interval mode uses */N rather than IntervalTrigger because IntervalTrigger
    anchors to process start, so every rebuild would move the run times.
    """
    if settings.get_setting("PIPELINE_MODE") == PipelineMode.INTERVAL:
        return CronTrigger(
            hour=f"*/{settings.get_setting('PIPELINE_EVERY_N_HOURS')}",
            minute=settings.get_setting("PIPELINE_AT_MINUTE"),
            timezone=TIMEZONE,
        )
    at: time = settings.get_setting("PIPELINE_AT_TIME")
    return CronTrigger(hour=at.hour, minute=at.minute, timezone=TIMEZONE)


def retention_trigger() -> CronTrigger:
    at: time = settings.get_setting("RETENTION_AT_TIME")
    return CronTrigger(hour=at.hour, minute=at.minute, timezone=TIMEZONE)


def _retention_job() -> None:
    """Retention borrows the pipeline's lock instead of relying on a clock gap.

    Any user-set interval that divides 24 includes midnight, so no validation can
    keep these two apart; mutual exclusion can. Skipping is safe — the deletes are
    idempotent and run again tomorrow.
    """
    if not try_acquire_lock_for_retention():
        logger.info("Retention skipped: a pipeline run is in progress")
        return
    try:
        delete_old_jobs()
    finally:
        release_run_lock()


def apply_schedule() -> None:
    """Install or re-install both jobs from current settings. Safe before start()."""
    scheduler.add_job(
        _retention_job,
        retention_trigger(),
        id=RETENTION_JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
    )
    if settings.get_setting("PIPELINE_ENABLED"):
        scheduler.add_job(
            run_pipeline,
            pipeline_trigger(),
            args=[RunTrigger.SCHEDULE.value],
            id=PIPELINE_JOB_ID,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            misfire_grace_time=MISFIRE_GRACE_SECONDS,
        )
    elif scheduler.get_job(PIPELINE_JOB_ID):
        # Disabled means no scheduled job at all. Manual triggers still work:
        # they add their own one-off date job.
        scheduler.remove_job(PIPELINE_JOB_ID)


@dataclass(frozen=True)
class SchedulePlan:
    """The five values that decide when the two jobs fire. They are only ever
    passed together, and only ever to answer "do these collide?"."""

    mode: str
    at_time: time
    every_n_hours: int
    at_minute: int
    retention_at: time

    @classmethod
    def from_parsed(cls, parsed: dict) -> "SchedulePlan":
        return cls(
            mode=parsed["PIPELINE_MODE"],
            at_time=parsed["PIPELINE_AT_TIME"],
            every_n_hours=parsed["PIPELINE_EVERY_N_HOURS"],
            at_minute=parsed["PIPELINE_AT_MINUTE"],
            retention_at=parsed["RETENTION_AT_TIME"],
        )


def conflict_message(plan: SchedulePlan) -> str | None:
    """Non-null when the pipeline would fire at the exact retention time."""
    mode, at_time = plan.mode, plan.at_time
    every_n_hours, at_minute, retention_at = plan.every_n_hours, plan.at_minute, plan.retention_at
    if mode == PipelineMode.DAILY:
        if (at_time.hour, at_time.minute) == (retention_at.hour, retention_at.minute):
            return "The pipeline and retention are both set to " f"{at_time:%H:%M}."
        return None
    if retention_at.minute == at_minute and retention_at.hour % every_n_hours == 0:
        return (
            f"Every {every_n_hours}h at :{at_minute:02d} includes "
            f"{retention_at:%H:%M}, when retention runs."
        )
    return None


def current_conflict() -> str | None:
    return conflict_message(
        SchedulePlan.from_parsed({key: settings.get_setting(key) for key in settings.SETTINGS})
    )


def next_run_at() -> datetime | None:
    job = scheduler.get_job(PIPELINE_JOB_ID)
    return getattr(job, "next_run_time", None) if job else None


def describe() -> str:
    if not settings.get_setting("PIPELINE_ENABLED"):
        return "Manual only"
    if settings.get_setting("PIPELINE_MODE") == PipelineMode.INTERVAL:
        hours = settings.get_setting("PIPELINE_EVERY_N_HOURS")
        return f"Every {hours}h at :{settings.get_setting('PIPELINE_AT_MINUTE'):02d}"
    return f"Daily at {settings.get_setting('PIPELINE_AT_TIME'):%H:%M}"


def state() -> dict:
    next_run = next_run_at()
    return {
        "enabled": settings.get_setting("PIPELINE_ENABLED"),
        "mode": settings.get_setting("PIPELINE_MODE"),
        "every_n_hours": settings.get_setting("PIPELINE_EVERY_N_HOURS"),
        "at_minute": settings.get_setting("PIPELINE_AT_MINUTE"),
        "at_time": f"{settings.get_setting('PIPELINE_AT_TIME'):%H:%M}",
        "retention_at_time": f"{settings.get_setting('RETENTION_AT_TIME'):%H:%M}",
        "allowed_interval_hours": list(settings.ALLOWED_INTERVAL_HOURS),
        "timezone": str(TIMEZONE),
        "description": describe(),
        "next_run_at": next_run.isoformat() if next_run else None,
        "conflict": current_conflict(),
    }
