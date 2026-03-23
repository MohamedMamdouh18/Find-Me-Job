from fastapi import FastAPI

from .routes import cv_router, db_router, jobs_router, params_router

app = FastAPI()

app.include_router(cv_router)
app.include_router(db_router)
app.include_router(jobs_router)
app.include_router(params_router)
