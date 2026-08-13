"""Telemetry event envelope + per-type props, as a Pydantic discriminated union.

The engine posts a JSON envelope with a ``event`` discriminator. Each event type
carries a typed ``props`` object. Unknown event types are rejected at validation.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

EventType = Literal[
    "player_load",
    "player_view",
    "bid_request",
    "ad_request",
    "bid_response",
    "auction_win",
    "impression",
    "ad_complete",
    "ad_error",
    "no_demand",
]


class Consent(BaseModel):
    gdpr: bool | None = None
    tcString: str | None = None
    usp: str | None = None
    gpp: str | None = None


# --- per-type props -------------------------------------------------------


class PlayerLoadProps(BaseModel):
    referrer: str | None = None
    viewport: str | None = None
    placement: str | None = None


class PlayerViewProps(BaseModel):
    """Slot crossed the viewability threshold and the auction was released."""

    placement: str | None = None
    delayMs: int | None = None  # time from player_load to the slot entering view


class BidRequestProps(BaseModel):
    bidders: list[str] = []
    timeout: int | None = None


class AdRequestProps(BaseModel):
    """A VAST call to the ad server. Fired on EVERY render path, including the
    fallbacks that never ran a Prebid auction — this is the fill denominator."""

    placement: str | None = None
    wonBid: bool | None = None  # carries Prebid targeting vs. house/direct fallthrough


class BidResponseProps(BaseModel):
    bidder: str
    cpm: float | None = None
    currency: str | None = None
    status: Literal["bid", "no-bid", "timeout", "error"]
    latencyMs: int | None = None


class AuctionWinProps(BaseModel):
    bidder: str
    cpmRaw: float
    cpmBiased: float
    hbPb: str | None = None
    floorApplied: bool | None = None


class ImpressionProps(BaseModel):
    adId: str | None = None
    creativeId: str | None = None
    adDuration: float | None = None


class AdCompleteProps(BaseModel):
    viewedPct: float | None = None
    quartiles: list[int] | None = None
    # A skipped ad still ends the break and still triggers a refresh cycle, but
    # it is not a completed view — keep the two distinguishable in reporting.
    skipped: bool | None = None


class AdErrorProps(BaseModel):
    errorCode: str | None = None
    phase: str | None = None
    fallbackServed: bool | None = None


# --- envelope -------------------------------------------------------------


class _Envelope(BaseModel):
    v: int = 1
    ts: int | None = None  # client epoch ms
    eventId: str
    account: str
    placementId: str | None = None
    adUnitPath: str | None = None
    pageUrl: str | None = None
    sessionId: str | None = None
    # Ad-opportunity identity. Optional so engines older than 2.7.0 (which emit
    # neither) keep ingesting — their rows simply have a null auction_id.
    auctionId: str | None = None
    refreshIndex: int | None = None
    engineVersion: str | None = None
    consent: Consent | None = None


class PlayerLoadEvent(_Envelope):
    event: Literal["player_load"]
    props: PlayerLoadProps = PlayerLoadProps()


class PlayerViewEvent(_Envelope):
    event: Literal["player_view"]
    props: PlayerViewProps = PlayerViewProps()


class BidRequestEvent(_Envelope):
    event: Literal["bid_request"]
    props: BidRequestProps = BidRequestProps()


class AdRequestEvent(_Envelope):
    event: Literal["ad_request"]
    props: AdRequestProps = AdRequestProps()


class BidResponseEvent(_Envelope):
    event: Literal["bid_response"]
    props: BidResponseProps


class AuctionWinEvent(_Envelope):
    event: Literal["auction_win"]
    props: AuctionWinProps


class ImpressionEvent(_Envelope):
    event: Literal["impression"]
    props: ImpressionProps = ImpressionProps()


class AdCompleteEvent(_Envelope):
    event: Literal["ad_complete"]
    props: AdCompleteProps = AdCompleteProps()


class AdErrorEvent(_Envelope):
    event: Literal["ad_error"]
    props: AdErrorProps = AdErrorProps()


class NoDemandEvent(_Envelope):
    event: Literal["no_demand"]
    props: AdErrorProps = AdErrorProps()


AnyEvent = Annotated[
    PlayerLoadEvent
    | PlayerViewEvent
    | BidRequestEvent
    | AdRequestEvent
    | BidResponseEvent
    | AuctionWinEvent
    | ImpressionEvent
    | AdCompleteEvent
    | AdErrorEvent
    | NoDemandEvent,
    Field(discriminator="event"),
]

event_adapter: TypeAdapter[AnyEvent] = TypeAdapter(AnyEvent)
