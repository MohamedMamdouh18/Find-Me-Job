"""add starred_companies table

Revision ID: a1b2c3d4e5f6
Revises: c2b7f1a9d4e3
Create Date: 2026-04-15 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "c2b7f1a9d4e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "starred_companies",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("careers_url", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_name"),
    )
    op.create_index(
        "ix_starred_companies_company_name",
        "starred_companies",
        ["company_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_starred_companies_company_name", table_name="starred_companies")
    op.drop_table("starred_companies")
