"""add blocked_companies and workflow_runs

Revision ID: e8f5a3c91d24
Revises: d7e4c2f81b60
Create Date: 2026-08-19 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8f5a3c91d24"
down_revision: Union[str, Sequence[str], None] = "d7e4c2f81b60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "blocked_companies",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_name"),
    )
    op.create_index(
        "ix_blocked_companies_company_name", "blocked_companies", ["company_name"], unique=True
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("jobs_scraped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_scored", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_matched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_runs_started_at", "workflow_runs", ["started_at"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_started_at", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index("ix_blocked_companies_company_name", table_name="blocked_companies")
    op.drop_table("blocked_companies")
