import asyncio

from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .routes import cv_router, jobs_router, params_router, email_router, starred_router
from contextlib import asynccontextmanager
from .database.core import delete_old_jobs, run_migrations
from . import shared
from .shared import detect_tunnel_url_and_send_notification

scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    run_migrations()
    delete_old_jobs()
    scheduler.add_job(delete_old_jobs, CronTrigger(hour=0, minute=0))
    scheduler.start()

    asyncio.create_task(detect_tunnel_url_and_send_notification())

    yield

    # SHUTDOWN
    if shared.email_service:
        shared.email_service.quit()
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)

app.include_router(cv_router)
app.include_router(jobs_router)
app.include_router(params_router)
app.include_router(email_router)
app.include_router(starred_router)
