from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..database import get_session
from ..database.repositories.sources import SourceRepository
from ..schemas.settings import SourceToggle
from ..scrapers import SOURCE_LABELS

sources_router = APIRouter(prefix="/api/sources", tags=["sources"])


@sources_router.get("")
def list_sources(session: Session = Depends(get_session)):
    """Every registered scraper and whether the next run will use it. Rows are
    reconciled at startup, so a registry entry with no row still appears here."""
    stored = {row.name: row for row in SourceRepository(session).get_all()}
    return [
        {
            "name": name,
            "label": stored[name].label if name in stored else label,
            "enabled": stored[name].enabled if name in stored else True,
        }
        for name, label in SOURCE_LABELS.items()
    ]


@sources_router.put("/{name}")
def set_source_enabled(name: str, body: SourceToggle, session: Session = Depends(get_session)):
    if name not in SOURCE_LABELS:
        raise HTTPException(status_code=404, detail=f"Unknown source: {name}")

    SourceRepository(session).set_enabled(name, body.enabled, SOURCE_LABELS[name])
    session.commit()
    return {"name": name, "enabled": body.enabled}
