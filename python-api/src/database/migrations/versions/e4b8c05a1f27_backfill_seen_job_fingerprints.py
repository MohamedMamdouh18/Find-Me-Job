"""backfill seen_job fingerprints

Revision ID: e4b8c05a1f27
Revises: c9f2a71d43e8
Create Date: 2026-09-16

A separate revision rather than an edit to c9f2a71d43e8, because that one has already run
on installs that upgraded before the backfill was written: alembic will not run a stamped
revision again, so the data it was meant to reach would stay untouched forever.

Idempotent by construction — it only fills rows where the fingerprint is still null — so
it costs nothing on an install that already got the backfill, and nothing on a fresh one
where there is no history to fill.
"""

import hashlib
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4b8c05a1f27"
down_revision: Union[str, Sequence[str], None] = "c9f2a71d43e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Copied rather than imported, for the same reason as the previous revision: a migration
# must keep producing the value it produced the day it ran.
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


def upgrade() -> None:
    connection = op.get_bind()
    filled = 0
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
            filled += 1
    print(f"  backfilled {filled} seen_jobs fingerprints")


def downgrade() -> None:
    # Nothing to undo: the column and its index belong to the previous revision, and
    # clearing the values would only re-create the duplicates this fixed.
    pass
