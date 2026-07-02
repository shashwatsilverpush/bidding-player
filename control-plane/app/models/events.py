"""Append-only telemetry events.

Deliberately flat + typed so the table can later be mirrored 1:1 into a columnar
store (ClickHouse / BigQuery) without reshaping. Event-type-specific fields that
don't warrant a promoted column live in ``props`` (JSONB).
"""

from __future__ import annotations

from datetime import datetime
from functools import partial
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, gen_id


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_placement_type_ts", "placement_id", "event_type", "ts_server"),
        Index("ix_events_event_id", "event_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=partial(gen_id, "evt"))
    # client-generated UUID, enforced unique for idempotent ingestion
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    # epoch milliseconds from the client; server-side authoritative timestamp
    ts_client: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ts_server: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # denormalized identity for fast filtering
    account_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    placement_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    ad_unit_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # consent
    gdpr_applies: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tc_string: Mapped[str | None] = mapped_column(Text, nullable=True)

    # promoted win fields (raw AND biased — the engine inflates hb_pb via floor bias)
    cpm_raw: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    cpm_biased: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    hb_pb: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bidder: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # everything else, event-type specific
    props: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # enrichment
    ua: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
