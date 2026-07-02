"""Event ingestion: validate -> consent-gate -> enrich -> idempotent store."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import gen_id, utcnow
from app.models import Account, Event
from app.schemas.events import AnyEvent, AuctionWinEvent
from app.settings import get_settings


def lookup_country(ip: str | None) -> str | None:
    """Stub geo lookup. Wire a real GeoIP/MaxMind provider here later."""
    return None


async def _account_exists(session: AsyncSession, account_id: str) -> bool:
    res = await session.execute(select(Account.id).where(Account.id == account_id))
    return res.scalar_one_or_none() is not None


def _needs_consent_gating(event: AnyEvent) -> bool:
    """True when GDPR applies but no consent signal (TC string) is present."""
    c = event.consent
    if c is None:
        return False
    return bool(c.gdpr) and not c.tcString


async def ingest_event(
    session: AsyncSession,
    event: AnyEvent,
    *,
    ua: str | None,
    ip: str | None,
) -> str:
    """Store one event. Returns 'stored' | 'duplicate' | 'dropped_unknown_account'
    | 'dropped_consent'. Never raises for business outcomes."""
    settings = get_settings()

    # Unknown account -> drop silently (caller still returns 204 to avoid leaking).
    if not await _account_exists(session, event.account):
        return "dropped_unknown_account"

    anonymize = False
    if _needs_consent_gating(event):
        if settings.consent_mode == "drop":
            return "dropped_consent"
        anonymize = True  # store a minimal row

    props: dict[str, Any] = event.props.model_dump(exclude_none=True)

    row: dict[str, Any] = {
        "id": gen_id("evt"),
        "event_id": event.eventId,
        "event_type": event.event,
        "ts_client": event.ts,
        "ts_server": utcnow(),
        "account_id": event.account,
        "placement_id": event.placementId,
        "ad_unit_path": event.adUnitPath,
        "session_id": event.sessionId,
        "engine_version": event.engineVersion,
        "gdpr_applies": event.consent.gdpr if event.consent else None,
        "props": props,
    }

    if anonymize:
        # Minimal row: no precise page url, no IP-derived country, no consent string.
        row["page_url"] = None
        row["tc_string"] = None
        row["ua"] = None
        row["ip_country"] = None
    else:
        row["page_url"] = event.pageUrl
        row["tc_string"] = event.consent.tcString if event.consent else None
        row["ua"] = ua
        row["ip_country"] = lookup_country(ip)

    # Promote win fields into columns.
    if isinstance(event, AuctionWinEvent):
        row["bidder"] = event.props.bidder
        row["cpm_raw"] = event.props.cpmRaw
        row["cpm_biased"] = event.props.cpmBiased
        row["hb_pb"] = event.props.hbPb

    stmt = (
        pg_insert(Event)
        .values(**row)
        .on_conflict_do_nothing(index_elements=[Event.event_id])
        .returning(Event.id)
    )
    result = await session.execute(stmt)
    inserted = result.scalar_one_or_none()
    await session.commit()
    return "stored" if inserted is not None else "duplicate"


async def count_by_type(
    session: AsyncSession,
    *,
    placement_id: str | None,
    ts_from: Any | None,
    ts_to: Any | None,
) -> dict[str, int]:
    stmt = select(Event.event_type, func.count()).group_by(Event.event_type)
    if placement_id:
        stmt = stmt.where(Event.placement_id == placement_id)
    if ts_from is not None:
        stmt = stmt.where(Event.ts_server >= ts_from)
    if ts_to is not None:
        stmt = stmt.where(Event.ts_server <= ts_to)
    rows = (await session.execute(stmt)).all()
    return {row[0]: row[1] for row in rows}
