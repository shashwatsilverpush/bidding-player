"""Application configuration, sourced entirely from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://bp:bp@localhost:55432/control_plane"

    @field_validator("database_url")
    @classmethod
    def _force_asyncpg_driver(cls, v: str) -> str:
        """Managed Postgres (Shipyard, RDS, Neon, …) hands out ``postgres://`` /
        ``postgresql://`` URLs, which SQLAlchemy maps to the sync psycopg2 driver.
        This app is fully async, so coerce the scheme to the asyncpg driver."""
        for prefix in ("postgresql+psycopg2://", "postgresql://", "postgres://"):
            if v.startswith(prefix):
                return "postgresql+asyncpg://" + v[len(prefix) :]
        return v

    # Auth
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    admin_username: str = "admin"
    admin_password: str | None = None
    admin_password_hash: str | None = None

    # Telemetry / config delivery. Leave UNSET in deployed environments so the
    # beacon/config URL is derived from the incoming request host — then every
    # environment (staging/prod/preview) self-serves the correct URL with no
    # per-env secret. Set it only to force a specific base (e.g. local dev).
    public_base_url: str | None = None
    default_prebid_url: str = (
        "https://cdn.jsdelivr.net/gh/shashwatsilverpush/bidding-player@v2.5.2/prebid/prebid.js"
    )
    default_sample_rate: float = 1.0

    # Engine tag generation (mirrors index.html buildEngineFile). The engine CDN
    # artifact currently lives under shashwatsilverpush; override if it moves.
    engine_repo: str = "shashwatsilverpush/bidding-player"
    default_engine_version: str = "v2.5.2"
    # Local-dev override: when set (e.g. http://localhost:8080), generated tags
    # load engine/player.js + prebid/prebid.js from THIS base instead of jsDelivr,
    # so you can test unreleased engine changes locally before cutting a release.
    engine_base_url: str | None = None
    default_cache_url: str = "https://prebid.adnxs.com/pbc/v1/cache"
    default_div_id: str = "bp-video-slot"

    # Dev-only endpoints (demo-data seeder). Disable in production.
    allow_dev_endpoints: bool = True

    # Consent policy: "anonymize" | "drop"
    consent_mode: str = "anonymize"

    # CORS
    admin_cors_origins: str = "*"

    log_level: str = "INFO"

    def beacon_url(self, request_base: str | None = None) -> str:
        """Collector URL baked into generated tags. Prefer an explicit
        PUBLIC_BASE_URL; else the per-request host; else localhost. Forces a
        scheme so a scheme-less PUBLIC_BASE_URL (e.g. 'host.example') still yields
        an absolute https URL — a bare host would break on an HTTPS publisher page."""
        base = (self.public_base_url or request_base or "http://localhost:8000").strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            base = "https://" + base
        return f"{base}/e"

    @property
    def admin_cors_list(self) -> list[str]:
        return [o.strip() for o in self.admin_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
