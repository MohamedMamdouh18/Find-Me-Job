from fastapi import FastAPI

from .routes import cv_router, jobs_router, params_router
from contextlib import asynccontextmanager
from .database.core import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    init_db()
    yield

    # SHUTDOWN


app = FastAPI(lifespan=lifespan)

app.include_router(cv_router)
app.include_router(jobs_router)
app.include_router(params_router)
