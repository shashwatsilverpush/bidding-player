"""Admin: demand-partner catalog + per-publisher enablement."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.deps import AdminDep
from app.db import get_session
from app.models import DemandPartner, Publisher, PublisherDemand
from app.schemas.admin import (
    DemandPartnerCreate,
    DemandPartnerOut,
    DemandPartnerUpdate,
    PublisherDemandOut,
    PublisherDemandUpsert,
)

router = APIRouter(prefix="/v1/admin", tags=["demand"], dependencies=[AdminDep])

SessionDep = Depends(get_session)


def _pd_out(pd: PublisherDemand) -> PublisherDemandOut:
    return PublisherDemandOut(
        id=pd.id,
        publisher_id=pd.publisher_id,
        demand_partner_id=pd.demand_partner_id,
        demand_partner_code=pd.demand_partner.code,
        params=dict(pd.params_json or {}),
        floor=float(pd.floor) if pd.floor is not None else None,
        enabled=pd.enabled,
        created_at=pd.created_at,
        updated_at=pd.updated_at,
    )


# --- catalog --------------------------------------------------------------


@router.get("/demand-partners", response_model=list[DemandPartnerOut])
async def list_partners(session: AsyncSession = SessionDep):
    rows = (
        (await session.execute(select(DemandPartner).order_by(DemandPartner.code))).scalars().all()
    )
    return list(rows)


@router.post("/demand-partners", response_model=DemandPartnerOut, status_code=201)
async def create_partner(body: DemandPartnerCreate, session: AsyncSession = SessionDep):
    dp = DemandPartner(
        code=body.code,
        label=body.label,
        adapter_module=body.adapter_module,
        required_params=body.required_params,
    )
    session.add(dp)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "demand partner code already exists") from exc
    await session.refresh(dp)
    return dp


@router.patch("/demand-partners/{partner_id}", response_model=DemandPartnerOut)
async def update_partner(
    partner_id: str, body: DemandPartnerUpdate, session: AsyncSession = SessionDep
):
    dp = await session.get(DemandPartner, partner_id)
    if dp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "demand partner not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(dp, k, v)
    await session.commit()
    await session.refresh(dp)
    return dp


# --- per-publisher enablement --------------------------------------------


async def _partner_by_code(session: AsyncSession, code: str) -> DemandPartner:
    dp = (
        await session.execute(select(DemandPartner).where(DemandPartner.code == code))
    ).scalar_one_or_none()
    if dp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown demand partner '{code}'")
    return dp


@router.get("/publishers/{publisher_id}/demand", response_model=list[PublisherDemandOut])
async def list_publisher_demand(publisher_id: str, session: AsyncSession = SessionDep):
    if await session.get(Publisher, publisher_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "publisher not found")
    stmt = (
        select(PublisherDemand)
        .where(PublisherDemand.publisher_id == publisher_id)
        .options(selectinload(PublisherDemand.demand_partner))
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [_pd_out(pd) for pd in rows]


@router.put("/publishers/{publisher_id}/demand/{partner_code}", response_model=PublisherDemandOut)
async def upsert_publisher_demand(
    publisher_id: str,
    partner_code: str,
    body: PublisherDemandUpsert,
    session: AsyncSession = SessionDep,
):
    """Enable (or update) a demand partner for a publisher. Validates that all of
    the partner's required params are supplied."""
    if await session.get(Publisher, publisher_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "publisher not found")
    dp = await _partner_by_code(session, partner_code)

    missing = [p for p in dp.required_params if p not in body.params]
    if body.enabled and missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"missing required params for {partner_code}: {missing}",
        )

    existing = (
        await session.execute(
            select(PublisherDemand).where(
                PublisherDemand.publisher_id == publisher_id,
                PublisherDemand.demand_partner_id == dp.id,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        existing = PublisherDemand(
            publisher_id=publisher_id,
            demand_partner_id=dp.id,
            params_json=body.params,
            floor=body.floor,
            enabled=body.enabled,
        )
        session.add(existing)
    else:
        existing.params_json = body.params
        existing.floor = body.floor
        existing.enabled = body.enabled

    await session.commit()
    await session.refresh(existing)
    existing.demand_partner = dp
    return _pd_out(existing)


@router.delete("/publishers/{publisher_id}/demand/{partner_code}", status_code=204)
async def remove_publisher_demand(
    publisher_id: str, partner_code: str, session: AsyncSession = SessionDep
):
    dp = await _partner_by_code(session, partner_code)
    existing = (
        await session.execute(
            select(PublisherDemand).where(
                PublisherDemand.publisher_id == publisher_id,
                PublisherDemand.demand_partner_id == dp.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "enablement not found")
    await session.delete(existing)
    await session.commit()
