import asyncio
from contextlib import asynccontextmanager
import logging

from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from sqlmodel import Session

from . import shared
from .database.core import delete_old_jobs, engine, run_migrations
from .database.repositories import WorkflowRunRepository
from .routes import (
    backup_router,
    blocked_router,
    cv_router,
    email_router,
    jobs_router,
    params_router,
    runs_router,
    starred_router,
)
from .services.pipeline import run_pipeline
from .services.run_context import RunIdFilter
from .shared import TIMEZONE, detect_tunnel_url_and_send_notification, scheduler

# Configure stdlib logging format and run_id injection
log_handler = logging.StreamHandler()
log_handler.setFormatter(
    logging.Formatter("[%(asctime)s] %(levelname)-5s %(run_id)s %(name)s: %(message)s")
)
log_handler.addFilter(RunIdFilter())
logging.basicConfig(level=logging.INFO, handlers=[log_handler])


@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    run_migrations()
    delete_old_jobs()
    scheduler.add_job(
        delete_old_jobs, CronTrigger(hour=0, minute=0, timezone=TIMEZONE)
    )
    # Offset from delete_old_jobs: running retention deletion inside a live scrape
    # would race the pipeline's own writes.
    scheduler.add_job(
        run_pipeline,
        CronTrigger(hour=1, minute=0, timezone=TIMEZONE),
        args=["schedule"],
        id="pipeline",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()

    # Keep a reference so the task is not garbage collected mid-flight.
    tunnel_task = asyncio.create_task(detect_tunnel_url_and_send_notification())

    yield

    # SHUTDOWN
    tunnel_task.cancel()
    if shared.email_service:
        shared.email_service.quit()

    # Mark any in-flight runs as failed on shutdown
    try:
        with Session(engine) as session:
            WorkflowRunRepository(session).fail_running("server shutdown")
            session.commit()
    except Exception:
        logging.getLogger(__name__).exception("Could not mark in-flight runs failed on shutdown")

    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(cv_router)
app.include_router(jobs_router)
app.include_router(params_router)
app.include_router(email_router)
app.include_router(starred_router)
app.include_router(blocked_router)
app.include_router(runs_router)
app.include_router(backup_router)
