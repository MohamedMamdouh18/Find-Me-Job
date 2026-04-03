"""rename cover_letter and add email_sent status

Revision ID: 5d3a77dd5b96
Revises: b974d777716d
Create Date: 2026-03-31 20:50:27.919677

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5d3a77dd5b96"
down_revision: Union[str, Sequence[str], None] = "b974d777716d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # rename column — no data loss
    op.alter_column("filtered_jobs", "cover_letter", new_column_name="application_document")
    # enum is just a string in SQLite so no enum migration needed
    # user_status is stored as TEXT — adding email_sent works automatically
    # just update your Python enum class and SQLModel model


def downgrade():
    op.alter_column("filtered_jobs", "application_document", new_column_name="cover_letter")
