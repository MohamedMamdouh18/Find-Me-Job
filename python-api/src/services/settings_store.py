"""Glue between the app_settings table and the settings cache.

Kept out of services/settings.py so that module stays import-free: shared.py
imports settings at module scope, and settings importing the database back would
close the loop.
"""

import logging
import os

from sqlmodel import Session

from . import settings
from ..database.repositories import AppSettingRepository

logger = logging.getLogger(__name__)


def load_cache(session: Session) -> None:
    settings.set_cache(AppSettingRepository(session).get_all())


def seed_from_env(session: Session) -> int:
    """One-time copy of env values into missing rows. Caller commits.

    Deliberately not an Alembic data migration: a fresh install never runs
    migrations at all (create_all + stamp head), so a migration would seed
    existing installs only.
    """
    repo = AppSettingRepository(session)
    existing = repo.get_all()
    seeded = 0
    for key in settings.SETTINGS:
        if key in existing:
            continue
        raw = os.getenv(key)
        if not raw:
            continue
        try:
            settings.parse_setting(key, raw)
        except (ValueError, TypeError):
            logger.warning("Ignoring invalid %s=%r from the environment", key, raw)
            continue
        repo.set(key, raw.strip())
        seeded += 1
    return seeded


def save(session: Session, values: dict[str, str]) -> None:
    """Write validated values. Caller commits, then calls load_cache()."""
    repo = AppSettingRepository(session)
    for key, value in values.items():
        repo.set(key, value)
