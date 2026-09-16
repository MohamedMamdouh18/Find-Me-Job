"""company fetch columns and the job fingerprint

Revision ID: c9f2a71d43e8
Revises: b5c8e2f47a91
Create Date: 2026-09-16

The starred_companies table becomes the company list: it gains the split between "I want
to work here" and "scrape this every run", and the verdict of the careers-URL sniff.

seen_jobs gains a fingerprint, which is backfilled only where the material still exists.
That table is an id and a timestamp, so a job already scored and drained, or blocked,
has nothing to compute one from. A null fingerprint never matches, so those rows keep
deduplicating on id alone, exactly as they do today.
"""

import hashlib
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Duplicated from services/identity.py on purpose: a migration has to keep producing the
# same value it produced the day it ran, and importing application code would let a later
# refactor silently change what this wrote.
LEGAL_SUFFIXES = {
    "inc", "incorporated", "ltd", "limited", "llc", "llp", "plc", "gmbh", "ag", "bv",
    "nv", "oy", "ab", "corp", "corporation", "co", "company", "group", "holdings",
}


def _normalise(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9\s]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _normalise_company(name: str) -> str:
    words = _normalise(name).split()
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def _fingerprint(company: str, title: str, location: str) -> str:
    parts = f"{_normalise_company(company)}::{_normalise(title)}::{_normalise(location)}"
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()

revision: str = "c9f2a71d43e8"
down_revision: Union[str, Sequence[str], None] = "b5c8e2f47a91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "starred_companies",
        sa.Column("starred", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "starred_companies",
        sa.Column("in_workflow", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "starred_companies",
        sa.Column("fetch_method", sa.String(), nullable=False, server_default="unknown"),
    )
    op.add_column("starred_companies", sa.Column("fetch_note", sa.String(), nullable=True))
    op.add_column("starred_companies", sa.Column("ats", sa.String(), nullable=True))
    op.add_column("starred_companies", sa.Column("ats_token", sa.String(), nullable=True))
    op.add_column(
        "starred_companies", sa.Column("last_scraped_at", sa.DateTime(), nullable=True)
    )
    op.add_column("starred_companies", sa.Column("last_job_count", sa.Integer(), nullable=True))
    op.add_column(
        "starred_companies",
        sa.Column("consecutive_empty", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column("seen_jobs", sa.Column("fingerprint", sa.String(), nullable=True))
    op.create_index("ix_seen_jobs_fingerprint", "seen_jobs", ["fingerprint"])
    _backfill_fingerprints()


def _backfill_fingerprints() -> None:
    """Fill in what can be filled in, and leave the rest null.

    seen_jobs is an id and a timestamp, so a job that was scored and drained, or blocked,
    has nothing here to compute a fingerprint from. What it does have is filtered_jobs and
    pending_jobs, which still carry company, title and location for the ids they hold.

    Without this every pre-existing job is invisible to the new check, and the first run
    after the upgrade re-queues a duplicate of each one that a newly added source also
    carries. A null fingerprint never matches, so the rows this cannot reach keep
    deduplicating on id alone exactly as they did before.
    """
    connection = op.get_bind()
    seen = 0
    for table in ("filtered_jobs", "pending_jobs"):
        rows = connection.execute(
            sa.text(
                f"SELECT j.id, j.company, j.title, j.location FROM {table} j "
                "JOIN seen_jobs s ON s.id = j.id WHERE s.fingerprint IS NULL"
            )
        ).fetchall()
        for row in rows:
            connection.execute(
                sa.text("UPDATE seen_jobs SET fingerprint = :fp WHERE id = :id"),
                {"fp": _fingerprint(row[1] or "", row[2] or "", row[3] or ""), "id": row[0]},
            )
            seen += 1
    print(f"  backfilled {seen} seen_jobs fingerprints")


def downgrade() -> None:
    op.drop_index("ix_seen_jobs_fingerprint", table_name="seen_jobs")
    op.drop_column("seen_jobs", "fingerprint")
    for column in (
        "consecutive_empty",
        "last_job_count",
        "last_scraped_at",
        "ats_token",
        "ats",
        "fetch_note",
        "fetch_method",
        "in_workflow",
        "starred",
    ):
        op.drop_column("starred_companies", column)
