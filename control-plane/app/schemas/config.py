"""Placement engine config (stored in ``placement.config_json``) and the assembled
runtime config returned by ``GET /v1/config/{placement_id}``.

The field set mirrors the ``data-*`` attributes the engine reads and that the
existing tag generator (`index.html::buildEngineFile`) emits, so a tag built from
this config is byte-compatible with the engine.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class AdTagEntry(BaseModel):
    """One step of the ad-server waterfall.

    ``timeoutMs`` bounds how long the engine waits for this tag to produce a
    creative before moving on — a dead endpoint that never errors would
    otherwise hold the break open and starve every tag behind it.
    """

    model_config = {"extra": "forbid"}

    url: str
    label: str | None = None
    timeoutMs: int = Field(default=3000, ge=500, le=15000)

    @field_validator("url")
    @classmethod
    def _url_is_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("ad tag url must start with http:// or https://")
        return v


class PlacementConfig(BaseModel):
    """Engine knobs stored on a placement. Validated on write.

    Precedence for the assembled bidder list (see services/config_assembly):
    ``publisher_demand`` (enabled) defines the *set* and default params/floor;
    ``enabledBidders`` (if present) restricts that set to the listed codes;
    ``bidderOverrides`` merges per-bidder param overrides on top (placement wins).
    """

    model_config = {"extra": "forbid"}

    placement: Literal["instream", "outstream"] = "instream"
    timeout: int = Field(default=1200, ge=100, le=10000)
    # String so "0.00" can express an explicit zero bias (engine treats empty/absent as 0.10).
    bias: str = "0.00"
    floorMin: float | None = None
    floorMax: float | None = None

    # --- GAM / ad serving ---
    # Ad-server waterfall, tried in order until one fills. When set it is the
    # source of truth; `adTag` is kept in sync with entry #1 (see
    # `sync_ad_tags`) so engines older than 2.7.0 — which only read `data-tag` —
    # still receive a working primary tag instead of nothing.
    adTags: list[AdTagEntry] | None = None
    adTag: str | None = None  # GAM VAST tag URL -> data-tag (waterfall entry #1)
    cacheUrl: str | None = None  # Prebid cache endpoint -> data-cache
    prebidUrl: str | None = None  # Prebid bundle URL -> data-prebid-url
    divId: str | None = None  # mount div id -> data-div-id

    # --- player behavior ---
    video: str | None = None  # instream content video -> data-video
    sticky: bool = False
    # Hold the auction until the slot is >=50% in view. On by default: it lifts
    # viewability and keeps the cached VAST fresh at render time.
    lazy: bool = True
    # Re-auction after each ad break. OFF by default — refresh is a commercial
    # policy decision (some direct deals and GAM contracts forbid it), so it must
    # be opted into per placement rather than inherited silently.
    refresh: bool = False
    # Seconds between ad breaks. The engine independently floors this at 30s to
    # stay inside IAB/GAM refresh guidance, so a lower value here cannot burn
    # the publisher's inventory.
    refreshInterval: int = Field(default=30, ge=30, le=600)
    refreshMax: int = Field(default=10, ge=1, le=100)
    autoplay: bool = True
    muted: bool = True
    fluid: bool = True
    loop: bool = False
    preload: str = "metadata"
    vpaid: str = "insecure"
    # Overlay play/pause + mute buttons while an ad plays. On by default: IMA
    # supplies no such controls, and during an instream break its ad container
    # covers the content player's own control bar — without this the player has
    # no controls at all for the length of the ad.
    adControls: bool = True

    sampleRate: float | None = Field(default=None, ge=0.0, le=1.0)

    # optional per-placement demand tuning
    enabledBidders: list[str] | None = None
    bidderOverrides: dict[str, dict[str, Any]] | None = None

    @field_validator("bias")
    @classmethod
    def _bias_is_numeric_string(cls, v: str) -> str:
        try:
            float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError("bias must be a numeric string, e.g. '0.00'") from exc
        return v

    @model_validator(mode="after")
    def _sync_ad_tags(self) -> PlacementConfig:
        """Keep `adTag` and `adTags` from ever disagreeing.

        Two directions, both needed:
        - waterfall set → mirror entry #1 into `adTag`, so a pinned older engine
          (and `readiness`/`preflight`, which check `adTag`) still see a tag.
        - only `adTag` set → promote it to a one-entry waterfall, so every
          consumer downstream can assume the list exists.
        """
        if self.adTags:
            self.adTag = self.adTags[0].url
        elif self.adTag:
            self.adTags = [AdTagEntry(url=self.adTag, label="primary")]
        return self


class Bidder(BaseModel):
    bidder: str
    params: dict[str, Any]
    floor: float | None = None


class RuntimeConfig(BaseModel):
    """What the engine fetches at runtime. Shape kept stable under /v1/."""

    placement: str
    timeout: int
    bias: str
    floorMin: float | None
    floorMax: float | None
    adTag: str | None
    adTags: list[AdTagEntry]
    video: str | None
    sticky: bool
    lazy: bool
    refresh: bool
    refreshInterval: int
    refreshMax: int
    autoplay: bool
    muted: bool
    fluid: bool
    loop: bool
    preload: str
    vpaid: str
    adControls: bool
    divId: str
    cacheUrl: str
    bidders: list[Bidder]
    prebidUrl: str
    beaconUrl: str
    sampleRate: float
    account: str
    adUnitPath: str
    engineChannel: str
