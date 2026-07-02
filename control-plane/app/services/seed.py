"""Canonical demand-partner catalog.

Mirrors the engine's hardcoded ``BIDDER_CATALOG`` (bidding-player v2.5.0). This is
the source of truth for both the seed migration and test fixtures. The seed
migration inlines the same rows so it stays self-contained; keep them in sync.
"""

from __future__ import annotations

from typing import TypedDict

# Fixed id for the single bootstrap tenant (kept stable so publisher creation can
# default to it). Multi-account is supported by the data model for later phases.
BOOTSTRAP_ACCOUNT_ID = "acc_root"
BOOTSTRAP_ACCOUNT_NAME = "Root Account"


class DemandPartnerSeed(TypedDict):
    code: str
    label: str
    adapter_module: str
    required_params: list[str]


DEMAND_PARTNERS: list[DemandPartnerSeed] = [
    {
        "code": "limelightDigital",
        "label": "Limelight Digital",
        "adapter_module": "limelightDigitalBidAdapter",
        "required_params": ["host", "publisherId", "adUnitId", "adUnitType"],
    },
    {
        "code": "appnexus",
        "label": "AppNexus / Xandr",
        "adapter_module": "appnexusBidAdapter",
        "required_params": ["placementId"],
    },
    {
        "code": "rubicon",
        "label": "Magnite / Rubicon",
        "adapter_module": "rubiconBidAdapter",
        "required_params": ["accountId", "siteId", "zoneId"],
    },
    {
        "code": "pubmatic",
        "label": "PubMatic",
        "adapter_module": "pubmaticBidAdapter",
        "required_params": ["publisherId", "adSlot"],
    },
    {
        "code": "openx",
        "label": "OpenX",
        "adapter_module": "openxBidAdapter",
        "required_params": ["unit", "delDomain"],
    },
    {
        "code": "incrementx",
        "label": "IncrementX",
        "adapter_module": "incrementxBidAdapter",
        "required_params": ["placementId"],
    },
]
