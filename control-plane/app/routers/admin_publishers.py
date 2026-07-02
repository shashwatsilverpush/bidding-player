"""Admin CRUD for the tenant chain: publisher -> site -> ad_unit -> placement.

All routes require a valid admin token.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AdminDep
from app.db import get_session
from app.models import Account, AdUnit, Placement, Publisher, Site
from app.schemas.admin import (
    AdUnitCreate,
    AdUnitOut,
    AdUnitUpdate,
    PlacementCreate,
    PlacementOut,
    PlacementUpdate,
    PublisherCreate,
    PublisherOut,
    PublisherUpdate,
    SiteCreate,
    SiteOut,
    SiteUpdate,
)
from app.schemas.config import PlacementConfig
from app.services.seed import BOOTSTRAP_ACCOUNT_ID

router = APIRouter(prefix="/v1/admin", tags=["admin"], dependencies=[AdminDep])

SessionDep = Depends(get_session)


async def _get_or_404(session: AsyncSession, model: type[Any], obj_id: str, what: str) -> Any:
    obj = await session.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
    return obj


def _placement_out(p: Placement) -> PlacementOut:
    return PlacementOut(
        id=p.id,
        ad_unit_id=p.ad_unit_id,
        name=p.name,
        engine_channel=p.engine_channel,
        config=PlacementConfig.model_validate(p.config_json or {}),
        active=p.active,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


# --- publishers -----------------------------------------------------------


@router.post("/publishers", response_model=PublisherOut, status_code=201)
async def create_publisher(body: PublisherCreate, session: AsyncSession = SessionDep):
    account_id = body.account_id or BOOTSTRAP_ACCOUNT_ID
    if await session.get(Account, account_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "account not found")
    pub = Publisher(
        account_id=account_id,
        name=body.name,
        gam_network_code=body.gam_network_code,
        status=body.status,
    )
    session.add(pub)
    await session.commit()
    await session.refresh(pub)
    return pub


@router.get("/publishers", response_model=list[PublisherOut])
async def list_publishers(session: AsyncSession = SessionDep):
    rows = (await session.execute(select(Publisher).order_by(Publisher.created_at))).scalars().all()
    return list(rows)


@router.get("/publishers/{publisher_id}", response_model=PublisherOut)
async def get_publisher(publisher_id: str, session: AsyncSession = SessionDep):
    return await _get_or_404(session, Publisher, publisher_id, "publisher")


@router.patch("/publishers/{publisher_id}", response_model=PublisherOut)
async def update_publisher(
    publisher_id: str, body: PublisherUpdate, session: AsyncSession = SessionDep
):
    pub = await _get_or_404(session, Publisher, publisher_id, "publisher")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(pub, k, v)
    await session.commit()
    await session.refresh(pub)
    return pub


@router.delete("/publishers/{publisher_id}", status_code=204)
async def delete_publisher(publisher_id: str, session: AsyncSession = SessionDep):
    pub = await _get_or_404(session, Publisher, publisher_id, "publisher")
    await session.delete(pub)
    await session.commit()


# --- sites ----------------------------------------------------------------


@router.post("/publishers/{publisher_id}/sites", response_model=SiteOut, status_code=201)
async def create_site(publisher_id: str, body: SiteCreate, session: AsyncSession = SessionDep):
    await _get_or_404(session, Publisher, publisher_id, "publisher")
    site = Site(publisher_id=publisher_id, domain=body.domain, app_bundle=body.app_bundle)
    session.add(site)
    await session.commit()
    await session.refresh(site)
    return site


@router.get("/publishers/{publisher_id}/sites", response_model=list[SiteOut])
async def list_sites(publisher_id: str, session: AsyncSession = SessionDep):
    rows = (
        (await session.execute(select(Site).where(Site.publisher_id == publisher_id)))
        .scalars()
        .all()
    )
    return list(rows)


@router.get("/sites/{site_id}", response_model=SiteOut)
async def get_site(site_id: str, session: AsyncSession = SessionDep):
    return await _get_or_404(session, Site, site_id, "site")


@router.patch("/sites/{site_id}", response_model=SiteOut)
async def update_site(site_id: str, body: SiteUpdate, session: AsyncSession = SessionDep):
    site = await _get_or_404(session, Site, site_id, "site")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(site, k, v)
    await session.commit()
    await session.refresh(site)
    return site


@router.delete("/sites/{site_id}", status_code=204)
async def delete_site(site_id: str, session: AsyncSession = SessionDep):
    site = await _get_or_404(session, Site, site_id, "site")
    await session.delete(site)
    await session.commit()


# --- ad units -------------------------------------------------------------


@router.post("/sites/{site_id}/ad-units", response_model=AdUnitOut, status_code=201)
async def create_ad_unit(site_id: str, body: AdUnitCreate, session: AsyncSession = SessionDep):
    await _get_or_404(session, Site, site_id, "site")
    au = AdUnit(site_id=site_id, gam_ad_unit_path=body.gam_ad_unit_path, format=body.format)
    session.add(au)
    await session.commit()
    await session.refresh(au)
    return au


@router.get("/sites/{site_id}/ad-units", response_model=list[AdUnitOut])
async def list_ad_units(site_id: str, session: AsyncSession = SessionDep):
    rows = (await session.execute(select(AdUnit).where(AdUnit.site_id == site_id))).scalars().all()
    return list(rows)


@router.get("/ad-units/{ad_unit_id}", response_model=AdUnitOut)
async def get_ad_unit(ad_unit_id: str, session: AsyncSession = SessionDep):
    return await _get_or_404(session, AdUnit, ad_unit_id, "ad_unit")


@router.patch("/ad-units/{ad_unit_id}", response_model=AdUnitOut)
async def update_ad_unit(ad_unit_id: str, body: AdUnitUpdate, session: AsyncSession = SessionDep):
    au = await _get_or_404(session, AdUnit, ad_unit_id, "ad_unit")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(au, k, v)
    await session.commit()
    await session.refresh(au)
    return au


@router.delete("/ad-units/{ad_unit_id}", status_code=204)
async def delete_ad_unit(ad_unit_id: str, session: AsyncSession = SessionDep):
    au = await _get_or_404(session, AdUnit, ad_unit_id, "ad_unit")
    await session.delete(au)
    await session.commit()


# --- placements -----------------------------------------------------------


@router.post("/ad-units/{ad_unit_id}/placements", response_model=PlacementOut, status_code=201)
async def create_placement(
    ad_unit_id: str, body: PlacementCreate, session: AsyncSession = SessionDep
):
    await _get_or_404(session, AdUnit, ad_unit_id, "ad_unit")
    plc = Placement(
        ad_unit_id=ad_unit_id,
        name=body.name,
        engine_channel=body.engine_channel,
        config_json=body.config.model_dump(),
        active=body.active,
    )
    session.add(plc)
    await session.commit()
    await session.refresh(plc)
    return _placement_out(plc)


@router.get("/ad-units/{ad_unit_id}/placements", response_model=list[PlacementOut])
async def list_placements(ad_unit_id: str, session: AsyncSession = SessionDep):
    rows = (
        (await session.execute(select(Placement).where(Placement.ad_unit_id == ad_unit_id)))
        .scalars()
        .all()
    )
    return [_placement_out(p) for p in rows]


@router.get("/placements/{placement_id}", response_model=PlacementOut)
async def get_placement(placement_id: str, session: AsyncSession = SessionDep):
    plc = await _get_or_404(session, Placement, placement_id, "placement")
    return _placement_out(plc)


@router.patch("/placements/{placement_id}", response_model=PlacementOut)
async def update_placement(
    placement_id: str, body: PlacementUpdate, session: AsyncSession = SessionDep
):
    plc = await _get_or_404(session, Placement, placement_id, "placement")
    data = body.model_dump(exclude_unset=True)
    if "config" in data and body.config is not None:
        plc.config_json = body.config.model_dump()
        data.pop("config")
    for k, v in data.items():
        setattr(plc, k, v)
    await session.commit()
    await session.refresh(plc)
    return _placement_out(plc)


@router.delete("/placements/{placement_id}", status_code=204)
async def delete_placement(placement_id: str, session: AsyncSession = SessionDep):
    plc = await _get_or_404(session, Placement, placement_id, "placement")
    await session.delete(plc)
    await session.commit()
