"""ad-opportunity identity on events: auction_id + refresh_index

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-13

Ad refresh makes one page load produce many ad opportunities, so `session_id`
can no longer join an impression to the request that caused it. `auction_id` is
the per-opportunity join key; `refresh_index` is 0 for the first opportunity on
the page and increments per refresh cycle.

Both are nullable: rows written by engines older than 2.7.0 predate the fields,
and backfilling them is impossible (the identity never existed client-side).
Reporting must therefore treat NULL auction_id as "legacy, one opportunity per
session".
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("auction_id", sa.String(length=64), nullable=True))
    op.add_column("events", sa.Column("refresh_index", sa.Integer(), nullable=True))
    op.create_index("ix_events_auction_id", "events", ["auction_id"])


def downgrade() -> None:
    op.drop_index("ix_events_auction_id", table_name="events")
    op.drop_column("events", "refresh_index")
    op.drop_column("events", "auction_id")
