"""seed reference data: bootstrap account + demand-partner catalog

Revision ID: a1b2c3d4e5f6
Revises: 238f01f77ac1
Create Date: 2026-07-02

Inlines the 6 demand partners (mirrors app/services/seed.py::DEMAND_PARTNERS) so
the migration is self-contained. Keep the two in sync when adding a partner.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "238f01f77ac1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BOOTSTRAP_ACCOUNT_ID = "acc_root"

DEMAND_PARTNERS = [
    (
        "dp_limelight",
        "limelightDigital",
        "Limelight Digital",
        "limelightDigitalBidAdapter",
        ["host", "publisherId", "adUnitId", "adUnitType"],
    ),
    ("dp_appnexus", "appnexus", "AppNexus / Xandr", "appnexusBidAdapter", ["placementId"]),
    (
        "dp_rubicon",
        "rubicon",
        "Magnite / Rubicon",
        "rubiconBidAdapter",
        ["accountId", "siteId", "zoneId"],
    ),
    ("dp_pubmatic", "pubmatic", "PubMatic", "pubmaticBidAdapter", ["publisherId", "adSlot"]),
    ("dp_openx", "openx", "OpenX", "openxBidAdapter", ["unit", "delDomain"]),
    ("dp_incrementx", "incrementx", "IncrementX", "incrementxBidAdapter", ["placementId"]),
]


def upgrade() -> None:
    account = sa.table(
        "account",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
    )
    op.bulk_insert(account, [{"id": BOOTSTRAP_ACCOUNT_ID, "name": "Root Account"}])

    demand_partner = sa.table(
        "demand_partner",
        sa.column("id", sa.String),
        sa.column("code", sa.String),
        sa.column("label", sa.String),
        sa.column("adapter_module", sa.String),
        sa.column("required_params", postgresql.JSONB),
    )
    op.bulk_insert(
        demand_partner,
        [
            {
                "id": pid,
                "code": code,
                "label": label,
                "adapter_module": module,
                "required_params": params,
            }
            for (pid, code, label, module, params) in DEMAND_PARTNERS
        ],
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM demand_partner WHERE code IN "
        "('limelightDigital','appnexus','rubicon','pubmatic','openx','incrementx')"
    )
    op.execute(f"DELETE FROM account WHERE id = '{BOOTSTRAP_ACCOUNT_ID}'")
