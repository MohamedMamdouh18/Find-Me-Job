from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field

from .base_model import BaseModel
from ...shared import now


class JobSource(BaseModel, table=True):
    """One row per scraper, so a source can be turned off from the dashboard.

    Rows are reconciled from the scraper registry at startup rather than seeded by
    a migration, so registering a new module is a row and not a schema change. A
    source with no row at all counts as enabled: that keeps an upgrade silent and
    means the table only ever records a decision the user actually made.
    """

    __tablename__ = "sources"  # type: ignore[assignment]

    name: str = Field(primary_key=True)
    label: str
    # server_default matches migration b5c8e2f47a91 exactly: the fresh-install path
    # builds this table from the model and the upgrade path from the migration, and
    # a default present on only one of them is two different tables.
    enabled: bool = Field(default=True, sa_column_kwargs={"server_default": sa.true()})
    updated_at: datetime = Field(default_factory=now)
