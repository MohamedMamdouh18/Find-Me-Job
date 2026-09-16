"""add sources table

Revision ID: b5c8e2f47a91
Revises: a3f1c9b45e27
Create Date: 2026-09-15

One row per scraper, so a source can be turned off from the dashboard. No rows are
seeded here: run_migrations() builds a fresh database from the models and stamps
head instead of running this chain, so seeding in a migration would reach existing
installs only. The rows are reconciled from the scraper registry at startup.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5c8e2f47a91"
down_revision: Union[str, Sequence[str], None] = "a3f1c9b45e27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("sources")
