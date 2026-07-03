"""Placement engine config (stored in ``placement.config_json``) and the assembled
runtime config returned by ``GET /v1/config/{placement_id}``.

The field set mirrors the ``data-*`` attributes the engine reads and that the
existing tag generator (`index.html::buildEngineFile`) emits, so a tag built from
this config is byte-compatible with the engine.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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
    adTag: str | None = None  # GAM VAST tag URL -> data-tag
    cacheUrl: str | None = None  # Prebid cache endpoint -> data-cache
    prebidUrl: str | None = None  # Prebid bundle URL -> data-prebid-url
    divId: str | None = None  # mount div id -> data-div-id

    # --- player behavior ---
    video: str | None = None  # instream content video -> data-video
    sticky: bool = False
    autoplay: bool = True
    muted: bool = True
    fluid: bool = True
    loop: bool = False
    preload: str = "metadata"
    vpaid: str = "insecure"

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
    video: str | None
    sticky: bool
    autoplay: bool
    muted: bool
    fluid: bool
    loop: bool
    preload: str
    vpaid: str
    divId: str
    cacheUrl: str
    bidders: list[Bidder]
    prebidUrl: str
    beaconUrl: str
    sampleRate: float
    account: str
    adUnitPath: str
    engineChannel: str
