"""Application configuration, sourced entirely from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://bp:bp@localhost:55432/control_plane"

    # Auth
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    admin_username: str = "admin"
    admin_password: str | None = None
    admin_password_hash: str | None = None

    # Telemetry / config delivery
    public_base_url: str = "http://localhost:8000"
    default_prebid_url: str = (
        "https://cdn.jsdelivr.net/gh/shashwatsilverpush/bidding-player@v2.5.0/prebid/prebid.js"
    )
    default_sample_rate: float = 1.0

    # Engine tag generation (mirrors index.html buildEngineFile). The engine CDN
    # artifact currently lives under shashwatsilverpush; override if it moves.
    engine_repo: str = "shashwatsilverpush/bidding-player"
    default_engine_version: str = "v2.5.0"
    default_cache_url: str = "https://prebid.adnxs.com/pbc/v1/cache"
    default_div_id: str = "bp-video-slot"

    # Dev-only endpoints (demo-data seeder). Disable in production.
    allow_dev_endpoints: bool = True

    # Consent policy: "anonymize" | "drop"
    consent_mode: str = "anonymize"

    # CORS
    admin_cors_origins: str = "*"

    log_level: str = "INFO"

    @property
    def beacon_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/e"

    @property
    def admin_cors_list(self) -> list[str]:
        return [o.strip() for o in self.admin_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
