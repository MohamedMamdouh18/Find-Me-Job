"""add filtered_jobs indexes and purge orphaned status history

Revision ID: d7e4c2f81b60
Revises: a1b2c3d4e5f6
Create Date: 2026-08-18 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d7e4c2f81b60"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (index name, table, columns) — covers every filter/sort path used by the dashboard
INDEXES = [
    ("ix_filtered_jobs_updated_at", "filtered_jobs", ["updated_at"]),
    ("ix_filtered_jobs_created_at", "filtered_jobs", ["created_at"]),
    ("ix_filtered_jobs_score", "filtered_jobs", ["score"]),
    ("ix_filtered_jobs_company", "filtered_jobs", ["company"]),
    ("ix_filtered_jobs_website", "filtered_jobs", ["website"]),
    ("ix_filtered_jobs_location", "filtered_jobs", ["location"]),
    # default dashboard view filters on both statuses then sorts by updated_at
    ("ix_filtered_jobs_status_updated", "filtered_jobs", ["ai_status", "user_status", "updated_at"]),
    ("ix_pending_jobs_created_at", "pending_jobs", ["created_at"]),
    ("ix_seen_jobs_seen_at", "seen_jobs", ["seen_at"]),
]


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)

    # history rows were never cleaned up when their job was deleted or purged
    op.execute(
        "DELETE FROM job_status_history "
        "WHERE job_id NOT IN (SELECT id FROM filtered_jobs)"
    )


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
