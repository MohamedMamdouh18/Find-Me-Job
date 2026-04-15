"""add job_status_history table

Revision ID: c2b7f1a9d4e3
Revises: 5d3a77dd5b96
Create Date: 2026-04-12 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "c2b7f1a9d4e3"
down_revision: Union[str, Sequence[str], None] = "5d3a77dd5b96"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_status_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["filtered_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_status_history_job_id",
        "job_status_history",
        ["job_id"],
    )

    # Backfill: seed one history row per existing filtered_job using its
    # current status + updated_at so the timeline is non-empty after migration.
    op.execute(
        """
        INSERT INTO job_status_history (job_id, status, changed_at)
        SELECT id, user_status, updated_at FROM filtered_jobs
        """
    )


def downgrade() -> None:
    op.drop_index("ix_job_status_history_job_id", table_name="job_status_history")
    op.drop_table("job_status_history")
