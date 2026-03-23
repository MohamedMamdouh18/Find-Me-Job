import os

from docx import Document
from fastapi import APIRouter

from ..shared import CV_PATH, PARAMS_DIR

resources_router = APIRouter(prefix="/api/resources", tags=["api", "resources"])


@resources_router.get("/cv")
def get_cv():
    doc = Document(CV_PATH)
    text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    return {"cv": text}


@resources_router.get("/param/{name}")
def get_param(name: str):
    path = os.path.join(PARAMS_DIR, f"{name}.txt")
    if not os.path.exists(path):
        return {"error": f"param '{name}' not found"}
    with open(path, "r") as f:
        return {"param": f.read()}
