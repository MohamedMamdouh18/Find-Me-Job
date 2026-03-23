from fastapi import FastAPI

from .routes import db_router, resources_router

app = FastAPI()

app.include_router(db_router)
app.include_router(resources_router)
