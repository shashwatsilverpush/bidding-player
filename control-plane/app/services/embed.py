"""Generate the publisher `<script>` embed tag from stored config.

This is a faithful server-side port of the engine repo's tag generator
(`index.html::buildEngineFile`) so the emitted tag is byte-compatible with the
engine's expected ``data-*`` attributes. The only difference is the source of the
values: here they come from the database (placement config + enabled demand
partners) instead of hand-typed form fields.
"""

from __future__ import annotations

import json

from app.schemas.config import RuntimeConfig
from app.settings import Settings


def _jsdelivr(repo: str, version: str, path: str) -> str:
    return f"https://cdn.jsdelivr.net/gh/{repo}@{version}/{path}"


def build_embed_tag(cfg: RuntimeConfig, settings: Settings) -> str:
    """Return the `<script …></script>` string for a placement.

    ``cfg.engineChannel`` == "auto" emits the auto-updating loader (engine version
    resolved at runtime; ``data-prebid-url`` carries a ``__VER__`` token the loader
    substitutes). Anything else pins the exact engine version.
    """
    repo = settings.engine_repo
    version = settings.default_engine_version
    is_auto = cfg.engineChannel == "auto"

    if is_auto:
        src = _jsdelivr(repo, "2", "engine/loader.js")
        # Rewrite the prebid path to carry the loader's __VER__ token.
        prebid_out = _prebid_with_token(cfg.prebidUrl, repo)
    else:
        src = _jsdelivr(repo, version, "engine/player.js")
        prebid_out = cfg.prebidUrl

    # data-bidders mirrors the engine contract: [{bidder, params}]. Per-bidder
    # floor is not an engine tag attribute (floors are global via data-floor-*).
    bidders = [{"bidder": b.bidder, "params": b.params} for b in cfg.bidders]
    bidders_json = json.dumps(bidders, separators=(",", ":"))
    safe_json = bidders_json.replace("<", "\\u003c").replace("'", "&#39;")

    is_outstream = cfg.placement == "outstream"
    lines: list[str] = [
        f'<script src="{_esc(src)}"',
        '        id="adtech-player-core"',
        f"        data-bidders='{safe_json}'",
        f'        data-tag="{_esc(cfg.adTag or "")}"',
        f'        data-timeout="{cfg.timeout}"',
        f'        data-bias="{cfg.bias}"',
    ]
    if cfg.floorMin is not None:
        lines.append(f'        data-floor-min="{cfg.floorMin:.2f}"')
    if cfg.floorMax is not None:
        lines.append(f'        data-floor-max="{cfg.floorMax:.2f}"')
    if is_outstream:
        lines.append('        data-placement="outstream"')
    else:
        lines.append(f'        data-video="{_esc(cfg.video or "")}"')
        if cfg.sticky:
            lines.append('        data-sticky="true"')
    lines += [
        f'        data-autoplay="{_b(cfg.autoplay)}"',
        f'        data-muted="{_b(cfg.muted)}"',
        f'        data-fluid="{_b(cfg.fluid)}"',
    ]
    if not is_outstream:
        lines.append(f'        data-loop="{_b(cfg.loop)}"')
    lines += [
        f'        data-preload="{cfg.preload}"',
        f'        data-vpaid="{cfg.vpaid}"',
        f'        data-div-id="{_esc(cfg.divId)}"',
        f'        data-cache="{_esc(cfg.cacheUrl)}"',
        f'        data-prebid-url="{_esc(prebid_out)}"',
        "        async></script>",
    ]
    return "\n".join(lines)


def _prebid_with_token(prebid_url: str, repo: str) -> str:
    marker = f"{repo.split('/')[-1]}@"
    idx = prebid_url.find(marker)
    if idx == -1:
        return prebid_url
    after = prebid_url[idx + len(marker) :]
    slash = after.find("/")
    if slash == -1:
        return prebid_url
    path = after[slash + 1 :]
    return _jsdelivr(repo, "__VER__", path)


def _esc(s: str) -> str:
    return s.replace('"', "&quot;")


def _b(v: bool) -> str:
    return "true" if v else "false"
