"""Generate the publisher `<script>` embed tag from stored config.

The generator emits ONLY the thin "integrate-once" tag: the publisher pastes it
once and never edits it again. It carries just ``data-config-url`` +
``data-placement-id``; the engine fetches the live ``RuntimeConfig`` at load, so
demand (DSP add/remove), floors, bias, timeout and the VAST tag are all
backend-controlled and take effect on the next page load with no re-integration.

(The engine still *reads* the legacy ``data-*`` snapshot attributes, so any static
tag already deployed in the wild keeps working — but we no longer generate those.)
"""

from __future__ import annotations

from app.schemas.config import RuntimeConfig
from app.settings import Settings


def _jsdelivr(repo: str, version: str, path: str) -> str:
    return f"https://cdn.jsdelivr.net/gh/{repo}@{version}/{path}"


def _engine_src(cfg: RuntimeConfig, settings: Settings) -> str:
    """Resolve the `<script src>`: local engine (dev override), the auto-updating
    loader (``engineChannel == 'auto'``), or the pinned engine version."""
    repo = settings.engine_repo
    if settings.engine_base_url:
        return f"{settings.engine_base_url.rstrip('/')}/engine/player.js"
    if cfg.engineChannel == "auto":
        return _jsdelivr(repo, "2", "engine/loader.js")
    return _jsdelivr(repo, settings.default_engine_version, "engine/player.js")


def _config_base(cfg: RuntimeConfig) -> str:
    """Control-plane base for the runtime-config endpoint, derived from the beacon
    URL (same host). ``beacon_url()`` returns ``<base>/e``; strip the ``/e``."""
    b = cfg.beaconUrl or ""
    return b[:-2] if b.endswith("/e") else b


def build_embed_tag(cfg: RuntimeConfig, settings: Settings, placement_id: str) -> str:
    """Return the thin, self-configuring `<script …></script>` for a placement.

    Integrate once, never edit: the engine self-configures from the control plane
    via ``data-config-url``/``data-placement-id``. ``engineChannel == 'auto'`` emits
    the auto-updating loader; anything else pins the engine version — either way the
    runtime config is fetched, not baked.
    """
    lines = [
        f'<script src="{_esc(_engine_src(cfg, settings))}"',
        '        id="adtech-player-core"',
        f'        data-config-url="{_esc(_config_base(cfg) + "/v1/config")}"',
        f'        data-placement-id="{_esc(placement_id)}"',
        "        async></script>",
    ]
    return "\n".join(lines)


def _esc(s: str) -> str:
    return s.replace('"', "&quot;")
