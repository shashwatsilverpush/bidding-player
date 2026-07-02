"""Demand partner catalog + per-publisher enablement."""

from __future__ import annotations

from functools import partial
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, gen_id


class DemandPartner(Base):
    """The catalog of SSPs the platform supports (seeded from the engine catalog)."""

    __tablename__ = "demand_partner"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=partial(gen_id, "dp"))
    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    adapter_module: Mapped[str] = mapped_column(String(120), nullable=False)
    # list[str] of required param keys, e.g. ["host", "publisherId", "adUnitId"]
    required_params: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    enablements: Mapped[list[PublisherDemand]] = relationship(
        back_populates="demand_partner", cascade="all, delete-orphan"
    )


class PublisherDemand(Base):
    """A demand partner turned on for a given publisher, with its credentials/params."""

    __tablename__ = "publisher_demand"
    __table_args__ = (
        UniqueConstraint("publisher_id", "demand_partner_id", name="uq_publisher_demand"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=partial(gen_id, "pd"))
    publisher_id: Mapped[str] = mapped_column(
        ForeignKey("publisher.id", ondelete="CASCADE"), nullable=False, index=True
    )
    demand_partner_id: Mapped[str] = mapped_column(
        ForeignKey("demand_partner.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # bidder params for this publisher, e.g. {"host": "...", "publisherId": "..."}
    params_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    floor: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    publisher: Mapped[Any] = relationship("Publisher", back_populates="demand")
    demand_partner: Mapped[DemandPartner] = relationship(back_populates="enablements")
