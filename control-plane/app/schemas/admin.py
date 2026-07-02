"""Request/response schemas for admin CRUD and auth."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.config import PlacementConfig

# --- auth -----------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# --- base -----------------------------------------------------------------


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    created_at: datetime
    updated_at: datetime


# --- publisher ------------------------------------------------------------


class PublisherCreate(BaseModel):
    name: str
    account_id: str | None = None  # defaults to the bootstrap account
    gam_network_code: str | None = None
    status: Literal["active", "paused"] = "active"


class PublisherUpdate(BaseModel):
    name: str | None = None
    gam_network_code: str | None = None
    status: Literal["active", "paused"] | None = None


class PublisherOut(ORMModel):
    id: str
    account_id: str
    name: str
    gam_network_code: str | None
    status: str


# --- site -----------------------------------------------------------------


class SiteCreate(BaseModel):
    domain: str
    app_bundle: str | None = None


class SiteUpdate(BaseModel):
    domain: str | None = None
    app_bundle: str | None = None


class SiteOut(ORMModel):
    id: str
    publisher_id: str
    domain: str
    app_bundle: str | None


# --- ad unit --------------------------------------------------------------


class AdUnitCreate(BaseModel):
    gam_ad_unit_path: str
    format: Literal["video", "banner"] = "video"


class AdUnitUpdate(BaseModel):
    gam_ad_unit_path: str | None = None
    format: Literal["video", "banner"] | None = None


class AdUnitOut(ORMModel):
    id: str
    site_id: str
    gam_ad_unit_path: str
    format: str


# --- placement ------------------------------------------------------------


class PlacementCreate(BaseModel):
    name: str
    engine_channel: str = "auto"
    config: PlacementConfig = PlacementConfig()
    active: bool = True


class PlacementUpdate(BaseModel):
    name: str | None = None
    engine_channel: str | None = None
    config: PlacementConfig | None = None
    active: bool | None = None


class PlacementOut(ORMModel):
    id: str
    ad_unit_id: str
    name: str
    engine_channel: str
    config: PlacementConfig
    active: bool


# --- demand partner catalog ----------------------------------------------


class DemandPartnerCreate(BaseModel):
    code: str
    label: str
    adapter_module: str
    required_params: list[str] = []


class DemandPartnerUpdate(BaseModel):
    label: str | None = None
    adapter_module: str | None = None
    required_params: list[str] | None = None


class DemandPartnerOut(ORMModel):
    id: str
    code: str
    label: str
    adapter_module: str
    required_params: list[str]


# --- per-publisher demand enablement --------------------------------------


class PublisherDemandUpsert(BaseModel):
    params: dict = {}
    floor: float | None = None
    enabled: bool = True


class PublisherDemandOut(ORMModel):
    id: str
    publisher_id: str
    demand_partner_id: str
    demand_partner_code: str
    params: dict
    floor: float | None
    enabled: bool
