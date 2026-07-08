"""Admin CRUD for the tenant chain: publisher -> site -> ad_unit -> placement.

All routes require a valid admin token.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AdminDep
from app.db import get_session, utcnow
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
    """Fetch a live row. A soft-deleted row reads as 404 (use restore to bring back)."""
    obj = await session.get(model, obj_id)
    if obj is None or getattr(obj, "deleted_at", None) is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
    return obj


async def _count_live_children(
    session: AsyncSession, child: type[Any], fk: Any, parent_id: str
) -> int:
    stmt = select(func.count()).where(fk == parent_id, child.deleted_at.is_(None))
    return int((await session.execute(stmt)).scalar_one())


async def _stamp(
    session: AsyncSession, model: type[Any], fk: Any, parent_ids: list[str], ts: Any
) -> list[str]:
    """Soft-delete every live ``model`` row under ``parent_ids`` by loading them as
    ORM objects (so each change is picked up by the audit listeners) and stamping
    ``deleted_at``. Returns the affected ids for the next level down."""
    if not parent_ids:
        return []
    rows = (
        (await session.execute(select(model).where(fk.in_(parent_ids), model.deleted_at.is_(None))))
        .scalars()
        .all()
    )
    for r in rows:
        r.deleted_at = ts
    return [r.id for r in rows]


def _placement_out(p: Placement) -> PlacementOut:
    return PlacementOut(
        id=p.id,
        ad_unit_id=p.ad_unit_id,
        name=p.name,
        engine_channel=p.engine_channel,
        config=PlacementConfig.model_validate(p.config_json or {}),
        active=p.active,
        deleted_at=p.deleted_at,
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
    rows = (
        (
            await session.execute(
                select(Publisher)
                .where(Publisher.deleted_at.is_(None))
                .order_by(Publisher.created_at)
            )
        )
        .scalars()
        .all()
    )
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
async def delete_publisher(
    publisher_id: str,
    cascade: bool = Query(
        False, description="also soft-delete all child sites/ad-units/placements"
    ),
    session: AsyncSession = SessionDep,
):
    """Soft-delete a publisher. Refuses (409) if it still has live sites unless
    ``cascade=true``, in which case the whole subtree is soft-deleted in one go."""
    pub = await _get_or_404(session, Publisher, publisher_id, "publisher")
    children = await _count_live_children(session, Site, Site.publisher_id, publisher_id)
    if children and not cascade:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"publisher has {children} live site(s); pass ?cascade=true to delete them too",
        )
    ts = utcnow()
    if cascade:
        site_ids = await _stamp(session, Site, Site.publisher_id, [publisher_id], ts)
        au_ids = await _stamp(session, AdUnit, AdUnit.site_id, site_ids, ts)
        await _stamp(session, Placement, Placement.ad_unit_id, au_ids, ts)
    pub.deleted_at = ts
    await session.commit()


@router.post("/publishers/{publisher_id}/restore", response_model=PublisherOut)
async def restore_publisher(publisher_id: str, session: AsyncSession = SessionDep):
    """Un-delete a publisher. Children stay deleted; restore them individually."""
    pub = await session.get(Publisher, publisher_id)
    if pub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "publisher not found")
    if pub.deleted_at is not None:
        pub.deleted_at = None
        await session.commit()
        await session.refresh(pub)
    return pub


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
        (
            await session.execute(
                select(Site).where(Site.publisher_id == publisher_id, Site.deleted_at.is_(None))
            )
        )
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
async def delete_site(
    site_id: str,
    cascade: bool = Query(False, description="also soft-delete all child ad-units/placements"),
    session: AsyncSession = SessionDep,
):
    site = await _get_or_404(session, Site, site_id, "site")
    children = await _count_live_children(session, AdUnit, AdUnit.site_id, site_id)
    if children and not cascade:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"site has {children} live ad-unit(s); pass ?cascade=true to delete them too",
        )
    ts = utcnow()
    if cascade:
        au_ids = await _stamp(session, AdUnit, AdUnit.site_id, [site_id], ts)
        await _stamp(session, Placement, Placement.ad_unit_id, au_ids, ts)
    site.deleted_at = ts
    await session.commit()


@router.post("/sites/{site_id}/restore", response_model=SiteOut)
async def restore_site(site_id: str, session: AsyncSession = SessionDep):
    site = await session.get(Site, site_id)
    if site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "site not found")
    if site.deleted_at is not None:
        site.deleted_at = None
        await session.commit()
        await session.refresh(site)
    return site


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
    rows = (
        (
            await session.execute(
                select(AdUnit).where(AdUnit.site_id == site_id, AdUnit.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
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
async def delete_ad_unit(
    ad_unit_id: str,
    cascade: bool = Query(False, description="also soft-delete all child placements"),
    session: AsyncSession = SessionDep,
):
    au = await _get_or_404(session, AdUnit, ad_unit_id, "ad_unit")
    children = await _count_live_children(session, Placement, Placement.ad_unit_id, ad_unit_id)
    if children and not cascade:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"ad_unit has {children} live placement(s); pass ?cascade=true to delete them too",
        )
    ts = utcnow()
    if cascade:
        await _stamp(session, Placement, Placement.ad_unit_id, [ad_unit_id], ts)
    au.deleted_at = ts
    await session.commit()


@router.post("/ad-units/{ad_unit_id}/restore", response_model=AdUnitOut)
async def restore_ad_unit(ad_unit_id: str, session: AsyncSession = SessionDep):
    au = await session.get(AdUnit, ad_unit_id)
    if au is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ad_unit not found")
    if au.deleted_at is not None:
        au.deleted_at = None
        await session.commit()
        await session.refresh(au)
    return au


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
        (
            await session.execute(
                select(Placement).where(
                    Placement.ad_unit_id == ad_unit_id, Placement.deleted_at.is_(None)
                )
            )
        )
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
    plc.deleted_at = utcnow()
    await session.commit()


@router.post("/placements/{placement_id}/restore", response_model=PlacementOut)
async def restore_placement(placement_id: str, session: AsyncSession = SessionDep):
    plc = await session.get(Placement, placement_id)
    if plc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "placement not found")
    if plc.deleted_at is not None:
        plc.deleted_at = None
        await session.commit()
        await session.refresh(plc)
    return _placement_out(plc)
