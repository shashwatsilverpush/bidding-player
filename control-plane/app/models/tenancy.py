"""Tenant hierarchy: Account -> Publisher -> Site -> AdUnit -> Placement."""

from __future__ import annotations

from functools import partial
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, gen_id


class Account(Base):
    __tablename__ = "account"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=partial(gen_id, "acc"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    publishers: Mapped[list[Publisher]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class Publisher(Base):
    __tablename__ = "publisher"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=partial(gen_id, "pub"))
    account_id: Mapped[str] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    gam_network_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # status: active | paused
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    account: Mapped[Account] = relationship(back_populates="publishers")
    sites: Mapped[list[Site]] = relationship(
        back_populates="publisher", cascade="all, delete-orphan"
    )
    demand: Mapped[list[Any]] = relationship(
        "PublisherDemand", back_populates="publisher", cascade="all, delete-orphan"
    )


class Site(Base):
    __tablename__ = "site"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=partial(gen_id, "site"))
    publisher_id: Mapped[str] = mapped_column(
        ForeignKey("publisher.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    app_bundle: Mapped[str | None] = mapped_column(String(255), nullable=True)

    publisher: Mapped[Publisher] = relationship(back_populates="sites")
    ad_units: Mapped[list[AdUnit]] = relationship(
        back_populates="site", cascade="all, delete-orphan"
    )


class AdUnit(Base):
    __tablename__ = "ad_unit"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=partial(gen_id, "au"))
    site_id: Mapped[str] = mapped_column(
        ForeignKey("site.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gam_ad_unit_path: Mapped[str] = mapped_column(String(500), nullable=False)
    # format: video | banner
    format: Mapped[str] = mapped_column(String(20), nullable=False, default="video")

    site: Mapped[Site] = relationship(back_populates="ad_units")
    placements: Mapped[list[Placement]] = relationship(
        back_populates="ad_unit", cascade="all, delete-orphan"
    )


class Placement(Base):
    __tablename__ = "placement"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=partial(gen_id, "plc"))
    ad_unit_id: Mapped[str] = mapped_column(
        ForeignKey("ad_unit.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # "auto" (loader-managed) or a pinned "vX.Y.Z"
    engine_channel: Mapped[str] = mapped_column(String(40), nullable=False, default="auto")
    # engine knobs; validated against PlacementConfig on write
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    ad_unit: Mapped[AdUnit] = relationship(back_populates="placements")
