import asyncio
from contextlib import asynccontextmanager
import logging

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
    settings_router,
    starred_router,
)
from .services import settings_store
from .services.run_context import RunIdFilter
from .services.schedule import apply_schedule
from .shared import detect_tunnel_url_and_send_notification, scheduler

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
    # Seeded here rather than in a migration: a fresh install never runs migrations
    # (create_all + stamp head), so a data migration would reach existing installs only.
    with Session(engine) as session:
        settings_store.seed_from_env(session)
        session.commit()
        settings_store.load_cache(session)
    delete_old_jobs()
    # The jobstore is in-memory, so both jobs are rebuilt from app_settings on every boot.
    apply_schedule()
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
app.include_router(settings_router)
