import os
from fastapi import APIRouter, HTTPException
from ..shared import PARAMS_DIR

params_router = APIRouter(prefix="/api/params", tags=["params"])


@params_router.get("/{name}")
def get_param(name: str):
    path = os.path.join(PARAMS_DIR, f"{name}.txt")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Param '{name}' not found")
    with open(path, "r") as f:
        return {"param": f.read()}
