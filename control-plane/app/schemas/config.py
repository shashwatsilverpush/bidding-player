"""Placement engine config (stored in ``placement.config_json``) and the assembled
runtime config returned by ``GET /v1/config/{placement_id}``."""

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
    video: str | None = None
    sticky: bool = False
    sampleRate: float | None = Field(default=None, ge=0.0, le=1.0)
    prebidUrl: str | None = None

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
    video: str | None
    sticky: bool
    bidders: list[Bidder]
    prebidUrl: str
    beaconUrl: str
    sampleRate: float
    account: str
    adUnitPath: str
    engineChannel: str
