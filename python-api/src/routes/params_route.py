import os
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import shared
from ..shared import PARAMS_DIR

params_router = APIRouter(prefix="/api/params", tags=["params"])

# Param names map straight onto filenames, so keep them to a safe alphabet.
SAFE_PARAM_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
MAX_PARAM_BYTES = 256 * 1024


class ParamWrite(BaseModel):
    content: str


def _param_path(name: str) -> str:
    if not SAFE_PARAM_NAME.match(name):
        raise HTTPException(status_code=400, detail="Invalid param name")
    return os.path.join(PARAMS_DIR, f"{name}.txt")


@params_router.get("/dashboard-url")
def get_dashboard_url():
    """Return the public Cloudflare URL detected during startup, if available."""
    if not shared.DASHBOARD_URL:
        raise HTTPException(status_code=404, detail="Dashboard public URL not available yet")
    return {"url": shared.DASHBOARD_URL}


@params_router.get("/{name}")
def get_param(name: str):
    path = _param_path(name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Param '{name}' not found")
    with open(path, "r") as f:
        return {"param": f.read()}


@params_router.put("/{name}")
def put_param(name: str, body: ParamWrite):
    """Overwrite params/{name}.txt. Only files that already exist can be replaced."""
    path = _param_path(name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Param '{name}' not found")
    if len(body.content.encode("utf-8")) > MAX_PARAM_BYTES:
        raise HTTPException(status_code=413, detail="Param content too large")

    try:
        # Written in place: params/ is a bind mount, so a rename across it would fail.
        with open(path, "w") as f:
            f.write(body.content if body.content.endswith("\n") else body.content + "\n")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not write param: {e}")
    return {"status": "ok", "bytes": len(body.content.encode("utf-8"))}
