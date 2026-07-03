"""Assemble the runtime config for a placement.

Joins placement -> ad_unit -> site -> publisher and the publisher's enabled demand
partners into the flat shape the engine fetches.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AdUnit, Placement, Publisher, PublisherDemand, Site
from app.schemas.config import Bidder, PlacementConfig, RuntimeConfig
from app.settings import get_settings


class PlacementNotFound(Exception):
    pass


async def assemble_config(
    session: AsyncSession, placement_id: str, *, require_active: bool = True
) -> RuntimeConfig:
    """Assemble runtime config for a placement.

    ``require_active`` gates the public endpoint (inactive/paused -> 404). Admin
    tag generation passes ``require_active=False`` so a tag can be produced for a
    freshly created or paused placement.
    """
    where = [Placement.id == placement_id]
    if require_active:
        where.append(Placement.active.is_(True))
    stmt = (
        select(Placement)
        .where(*where)
        .options(
            selectinload(Placement.ad_unit).selectinload(AdUnit.site).selectinload(Site.publisher)
        )
    )
    placement = (await session.execute(stmt)).scalar_one_or_none()
    if placement is None:
        raise PlacementNotFound(placement_id)

    ad_unit = placement.ad_unit
    site = ad_unit.site
    publisher: Publisher = site.publisher
    if require_active and publisher.status != "active":
        raise PlacementNotFound(placement_id)

    cfg = PlacementConfig.model_validate(placement.config_json or {})

    bidders = await _assemble_bidders(session, publisher.id, cfg)

    settings = get_settings()
    return RuntimeConfig(
        placement=cfg.placement,
        timeout=cfg.timeout,
        bias=cfg.bias,
        floorMin=cfg.floorMin,
        floorMax=cfg.floorMax,
        adTag=cfg.adTag,
        video=cfg.video,
        sticky=cfg.sticky,
        autoplay=cfg.autoplay,
        muted=cfg.muted,
        fluid=cfg.fluid,
        loop=cfg.loop,
        preload=cfg.preload,
        vpaid=cfg.vpaid,
        divId=cfg.divId or settings.default_div_id,
        cacheUrl=cfg.cacheUrl or settings.default_cache_url,
        bidders=bidders,
        prebidUrl=cfg.prebidUrl or settings.default_prebid_url,
        beaconUrl=settings.beacon_url,
        sampleRate=cfg.sampleRate if cfg.sampleRate is not None else settings.default_sample_rate,
        account=publisher.account_id,
        adUnitPath=ad_unit.gam_ad_unit_path,
        engineChannel=placement.engine_channel,
    )


async def _assemble_bidders(
    session: AsyncSession, publisher_id: str, cfg: PlacementConfig
) -> list[Bidder]:
    """publisher_demand (enabled) defines the set + default params/floor;
    ``enabledBidders`` restricts it; ``bidderOverrides`` merges on top (placement wins)."""
    stmt = (
        select(PublisherDemand)
        .where(
            PublisherDemand.publisher_id == publisher_id,
            PublisherDemand.enabled.is_(True),
        )
        .options(selectinload(PublisherDemand.demand_partner))
    )
    rows = (await session.execute(stmt)).scalars().all()

    restrict = set(cfg.enabledBidders) if cfg.enabledBidders is not None else None
    overrides = cfg.bidderOverrides or {}

    bidders: list[Bidder] = []
    for pd in rows:
        code = pd.demand_partner.code
        if restrict is not None and code not in restrict:
            continue
        params = dict(pd.params_json or {})
        if code in overrides:
            params.update(overrides[code])
        bidders.append(
            Bidder(
                bidder=code,
                params=params,
                floor=float(pd.floor) if pd.floor is not None else None,
            )
        )
    return bidders
