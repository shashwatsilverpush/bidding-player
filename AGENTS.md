# AGENTS.md — Bidding Player Project Memory

> **Purpose:** This file is the authoritative source of project context for AI agents (Claude, etc.).
> Read this first before touching any code. Update this file on every release or significant feature addition.
> It replaces the need to scroll through long conversation histories.

---

## 1. Project Overview

**Name:** Bidding Player (`bidding-player`)  
**Owner:** aryanvani-projects  
**GitHub:** https://github.com/aryanvani-projects/bidding-player  
**Live Site:** https://aryanvani-projects.github.io/bidding-player/  
**CDN Base:** `https://cdn.jsdelivr.net/gh/aryanvani-projects/bidding-player@vX.Y.Z/`

A self-hosted video header-bidding player built on **Prebid.js + video.js + Google IMA SDK**.
The engine is a single script tag (`engine/player.js`) that publishers drop onto any page.
The dashboard (`index.html`) lets AdOps generate production tags, run sandbox simulations, and inspect bid flow — all in-browser with zero backend.

---

## 2. Current Version

**VERSION:** `2.4.0`  
All `@vX.Y.Z` CDN references in `index.html` and `demo/publisher-test.html` **must** match this value.
The `version-check.yml` CI workflow enforces this — it will fail the build if they drift.

To release a new version:
1. Edit code, bump `VERSION` file
2. Update `@vX.Y.Z` in `index.html` and `demo/publisher-test.html`
3. Commit & push to `main`
4. `git tag vX.Y.Z && git push --tags`
5. jsDelivr serves the new bytes within ~5 minutes of the tag

---

## 3. Repository Structure

```
/
├── index.html                   # Main dashboard (tag generator + sandbox + docs nav)
├── engine/
│   └── player.js                # The embeddable engine — the actual product
├── prebid/
│   └── prebid-custom.js         # Pre-built Prebid.js bundle (all 6 adapters)
├── demo/
│   └── publisher-test.html      # Live publisher integration demo page
├── docs.html                    # Technical reference (API, attributes, modules)
├── publisher-guide.html         # Publisher-facing integration guide (also renders to PDF)
├── publisher-guide.pdf          # Auto-regenerated from publisher-guide.html by CI
├── adops-guide.html             # AdOps-facing guide (line items, key-values, bias)
├── favicon.svg
├── VERSION                      # Single source of truth: "2.1.3"
└── .github/workflows/
    ├── build-prebid-bundle.yml  # Manual trigger: rebuilds prebid-custom.js
    ├── pages-deploy.yml         # Auto deploy to GitHub Pages on push to main
    ├── pdf-regen.yml            # Auto re-renders publisher-guide.pdf when HTML changes
    └── version-check.yml        # Fails CI if CDN @vX.Y.Z tags don't match VERSION
```

---

## 4. Engine (`engine/player.js`) — Key Internals

### Config attributes on the `<script>` tag

| Attribute | Default | Description |
|---|---|---|
| `data-bidders` | `[]` | JSON array of `{bidder, params}` objects |
| `data-tag` | required | GAM VAST tag URL |
| `data-timeout` | `1200` | Prebid auction timeout (ms) |
| `data-bias` | `0.10` | Floor bias added to winning CPM before bucketing. **Must be `"0.00"` to express zero** — empty string or omitting reverts to default 0.10 |
| `data-floor-min` | none | Reject winning bids below this CPM (falls through to house line item). Disabled when absent/non-numeric |
| `data-floor-max` | none | Cap the winning CPM at this value before bias + bucketing. Disabled when absent/non-numeric |
| `data-placement` | `instream` | `instream` plays the ad against content video via IMA pause/resume. `outstream` has no content video — slot stays collapsed until ≥50% in view, autoplays muted, collapses on completion/error |
| `data-video` | required (instream only) | MP4 content video URL. Ignored/omitted for outstream |
| `data-sticky` | `false` | Instream only. `true` makes the player float to the bottom-right corner when it scrolls out of view (keeps playing, ✕ to dismiss) and reflows the live IMA ad via `adsManager.resize()`. Ignored for outstream |
| `data-prebid-url` | required | jsDelivr URL to the Prebid.js bundle |
| `data-autoplay` | `true` | Autoplay the content video |
| `data-muted` | `true` | Mute on load |
| `data-fluid` | `true` | Fluid (responsive) sizing |
| `data-div-id` | required | ID of the `<div>` the player mounts into |
| `data-cache` | Prebid cache URL | Prebid cache endpoint |

### Critical bug fix (v2.1.1)
The original engine had `|| 0.10` which made it impossible to express zero bias:
```js
// WRONG (before v2.1.1):
floorBias: parseFloat(currentScript.getAttribute("data-bias")) || 0.10,

// CORRECT (v2.1.1+):
floorBias: (function (b) { return isNaN(b) ? 0.10 : b; })(parseFloat(currentScript.getAttribute("data-bias"))),
```

### Send All Bids (enabled v2.1.3)
`pbjs.setConfig({ enableSendAllBids: true })` — emits per-bidder GAM targeting keys:
`hb_pb_<bidder>`, `hb_adid_<bidder>`, `hb_size_<bidder>`, `hb_bidder_<bidder>`

---

## 5. Dashboard (`index.html`) — Key Sections

### Tabs
- **Production** — Tag generator for live publisher use
- **Sandbox** — Simulated auction with detailed phase logging
- **Docs** (inline links to docs.html, publisher-guide.html, adops-guide.html)

### Production Tab Structure
Organised into collapsible sections:
1. **Release** — version field, CDN URL preview
2. **Ad Serving** — GAM tag, Prebid cache URL, Prebid bundle URL
3. **Bidders** — multi-card picker (6 SSPs)
4. **Hosting & CDN** `<details>` — content video URL, div ID
5. **Player Behaviour** `<details>` — autoplay, mute, fluid, loop, preload, VPAID
6. **Auction Configuration** — timeout, floor bias (with **on/off toggle**)

### Sandbox Tab Structure
- **Auction Configuration** — mock CPM, timeout, floor bias (with **on/off toggle**, same as Production)
- **Bidder Picker** — same 6-card multi-select as Production
- **Run button** — triggers 7-phase simulation with detailed log

### Shared JavaScript Architecture

`BIDDER_CATALOG` is defined at script scope (not inside either tab's IIFE) so both pickers share it:

```js
const BIDDER_CATALOG = [
  { id: 'limelight',   label: 'Limelight Digital',  module: 'limelightDigitalBidAdapter',
    params: [{ key: 'host', ... }, { key: 'publisherId', ... }, { key: 'adUnitId', ... }, { key: 'adUnitType', ... }] },
  { id: 'appnexus',    label: 'AppNexus / Xandr',   module: 'appnexusBidAdapter',
    params: [{ key: 'placementId', ... }] },
  { id: 'rubicon',     label: 'Magnite / Rubicon',   module: 'rubiconBidAdapter',
    params: [{ key: 'accountId', ... }, { key: 'siteId', ... }, { key: 'zoneId', ... }] },
  { id: 'pubmatic',    label: 'PubMatic',            module: 'pubmaticBidAdapter',
    params: [{ key: 'publisherId', ... }, { key: 'adSlot', ... }] },
  { id: 'openx',       label: 'OpenX',               module: 'openxBidAdapter',
    params: [{ key: 'unit', ... }, { key: 'delDomain', ... }] },
  { id: 'incrementx',  label: 'IncrementX',          module: 'incrementxBidAdapter',
    params: [{ key: 'placementId', label: 'Placement ID', default: '', required: true }] },
];
```

Key functions (all script-scope):
- `renderBidderPicker(rootId, inputPrefix, onChange)` — renders cards, wires checkboxes
- `readBidders(rootSel, inputPrefix)` — reads checked bidders + their param values
- `applyBias(cpm)` — reads `#sandboxBiasToggle`, applies bias, buckets to Prebid granularity
- `validate()` — returns `{ok, msg, picker}`, checks sandbox picker has ≥1 bidder

### Bias Toggle Pattern (both tabs)

```html
<button id="sandboxBiasToggle" class="adops-toggle on" ...>
<span id="sandboxBiasStateLabel">On (+$0.05)</span>
```

```js
// Toggle click handler:
tgl.classList.toggle('on');
label.textContent = tgl.classList.contains('on') ? 'On (+$0.05)' : 'Off (raw bucketed CPM)';
```

The `applyBias()` function in the sandbox reads `#sandboxBiasToggle`.
The Production tag generator reads `#tglBias` and outputs `data-bias="0.00"` when OFF.

---

## 6. Bidder Catalog

| ID | Label | Prebid Adapter | Required Params |
|---|---|---|---|
| `limelight` | Limelight Digital | `limelightDigitalBidAdapter` | host, publisherId, adUnitId, adUnitType |
| `appnexus` | AppNexus / Xandr | `appnexusBidAdapter` | placementId |
| `rubicon` | Magnite / Rubicon | `rubiconBidAdapter` | accountId, siteId, zoneId |
| `pubmatic` | PubMatic | `pubmaticBidAdapter` | publisherId, adSlot |
| `openx` | OpenX | `openxBidAdapter` | unit, delDomain |
| `incrementx` | IncrementX | `incrementxBidAdapter` | placementId |

**Prebid bundle** in `prebid/prebid-custom.js` includes all 6 adapters + consent modules:
`consentManagementTcf`, `consentManagementUsp`, `consentManagementGpp`, `tcfControl`

---

## 7. CI / GitHub Actions

| Workflow | Trigger | Node | What it does |
|---|---|---|---|
| `pages-deploy.yml` | push to main | — | Deploys site to GitHub Pages |
| `version-check.yml` | push / PR | — | Fails if @vX.Y.Z in index.html/demo don't match VERSION |
| `pdf-regen.yml` | publisher-guide.html changed | — | Renders PDF with Chrome headless, commits back |
| `build-prebid-bundle.yml` | manual dispatch | **24** | Builds Prebid.js bundle from source, commits to prebid/ |

> **Note:** `build-prebid-bundle.yml` is the only workflow that uses `actions/setup-node`.
> Node version was updated from 20 → 24 in v2.1.3 release cycle (GitHub forced Node 24 by June 16 2026).

---

## 8. Sandbox Simulation Phases

The sandbox runs a 7-phase simulated auction when **Run Simulation** is clicked:

| Phase | Name | Key Logic |
|---|---|---|
| 1 | Auction Init | Read config (CPM, timeout, bias toggle, selected bidders) |
| 2 | Bid Requests | Iterate ticked bidders; assign deterministic CPMs (headline - i×0.20) |
| 3 | Bid Responses | Log each bidder's CPM + cache UUID |
| 4 | Auction | Determine winner by highest CPM |
| 5 | Price Bucketing | Call `applyBias()` → shows `Floor bias applied: +$0.05` or `(disabled)` |
| 6 | VAST Retrieval | Simulated cache fetch |
| 7 | IMA / Playback | Simulated ad playback + targeting key log |

Phase 5 log format (checked by test scripts):
- ON: `Floor bias applied: +$0.05`
- OFF: `Floor bias applied: (disabled)`

Final log line: `Final hb_pb value: $X.XX`

---

## 9. Key CSS Classes

| Class | Purpose |
|---|---|
| `.adops-subhead` | Section heading row in Production tab |
| `.adops-subhead-tag` | Version pill on section heading |
| `.adops-disclosure` | `<details>` collapsible panel wrapper |
| `.adops-disclosure-tag` | Pill inside `<summary>` |
| `.adops-disclosure-body` | Content inside collapsible |
| `.adops-inline-label` | Label that sits inline next to a toggle (NOT `display:block`) |
| `.adops-inline-toggle` | The toggle button itself |
| `.adops-toggle.on` | Active (enabled) state for any toggle button |
| `.sandbox-bidder-body` | Bidder card grid in Sandbox tab |
| `.sandbox-bidder-hint` | Helper text below sandbox bidder picker |

> **CSS specificity trap:** `.adops-field label { display:block }` was overriding `.adops-inline-label { display:flex }`.
> Fixed by qualifying: `.adops-field label.adops-inline-label { display:flex; ... }`.

---

## 10. Release History

### v2.4.0 (current)
- **Sticky / floating instream player** — `data-sticky="true"`. New `setupSticky()` in the engine wraps the instream mount in a flow-holding wrapper and uses an `IntersectionObserver` to pin the player `position:fixed` to the bottom-right corner when it scrolls out of view, restoring it inline on scroll-back. The wrapper reserves the original layout space (no jump). A ✕ button dismisses + pauses. The live IMA ad creative is reflowed to the docked size via `adsManager.resize()` (manager exposed as `container.__atpMgr`). Instream only — outstream already auto-collapses.
- **Dashboard toggle** — "Sticky / Floating Player" in Player Behaviour (defaults off); emits `data-sticky="true"` only when on and placement is instream.

### v2.3.0
- **Outstream video support** — `data-placement="outstream"`. New `setupOutstream()` renderer in the engine: the mount starts collapsed (`height:0`), an `IntersectionObserver` (≥50% threshold) holds the ad until the slot scrolls into view, then `adsManager.start()` fires (muted autoplay). The slot expands to 16:9 on `CONTENT_PAUSE_REQUESTED` and collapses again on `ALL_ADS_COMPLETED`/`AD_ERROR`. No content video required.
- **Engine render dispatch** — all auction render paths now go through `render()`, which routes to `setupOutstream()` or the existing `setupPlayer()` by `cfg.placement`. The Prebid adUnit `mediaTypes.video.context` is now `cfg.placement` (was hard-coded `"instream"`).
- **Dashboard placement selector** — Production tag generator gained a Placement dropdown (instream/outstream) in Ad Serving. Selecting outstream dims/disables the Video Content URL field and the generated tag emits `data-placement="outstream"` with `data-video` omitted.

### v2.2.0
- **Floor price controls** — `data-floor-min` (reject sub-floor bids → house line item) and `data-floor-max` (cap winning CPM before bias + bucketing). Wired into engine `bidsBackHandler`, the Production tag generator (toggle + input), and the sandbox simulation.
- **GAM Key-Value reference tab** — new dashboard tab documenting standard + per-bidder `hb_*` keys, the `%%PATTERN:hb_uuid%%` VAST creative macro, and line-item setup steps.

### v2.1.3
- **Send All Bids** — `enableSendAllBids: true` in `pbjs.setConfig()`. Per-bidder GAM keys now emitted: `hb_pb_<bidder>`, `hb_adid_<bidder>`, etc.
- **Sandbox Bias Toggle** — mirrored the Production bias on/off switch into the Sandbox simulation Auction Configuration table
- **Prebid bundle updated** — includes all 6 adapters (IncrementX added in v2.1.2)
- **Node 24 upgrade** — `build-prebid-bundle.yml` updated from Node 20 → 24
- **Docs sync** — `docs.html`, `publisher-guide.html`, `adops-guide.html` updated to @v2.1.3

### v2.1.2
- **IncrementX bidder** — added to `BIDDER_CATALOG` (requires `placementId`)
- **Prebid bundle rebuilt** — `incrementxBidAdapter` included
- `build-prebid-bundle.yml` default module list updated

### v2.1.1
- **Bias zero-coercion fix** — engine's `|| 0.10` replaced with `isNaN(b) ? 0.10 : b` so `data-bias="0.00"` works
- **Production bias toggle** — on/off switch added to Production tag generator Auction Configuration section. When OFF, outputs `data-bias="0.00"`
- **Sandbox multi-bidder picker** — 5-SSP (later 6) card picker added to Sandbox tab, mirroring Production
- **Multi-bidder simulation** — phases 2–5 iterate all ticked bidders with deterministic CPMs

### v2.1.0
- Initial multi-section Production tab UI (Release / Ad Serving / Bidders / Hosting & CDN / Player Behaviour)
- 5-bidder catalog (Limelight, AppNexus, Magnite, PubMatic, OpenX)
- Collapsible `<details>` panels for Hosting & CDN and Player Behaviour

---

## 11. Planned / Future Features

Priority order as of v2.4.0:

> **Shipped:** Floor price controls + GAM Key-Value reference (v2.2.0); Outstream video support (v2.3.0); Sticky / floating instream player (v2.4.0).

### Near-term (next sprint)
| # | Feature | Why |
|---|---|---|
| 1 | **Sandbox: Real Bid Request mode** | Fire real `pbjs.requestBids()` from sandbox; show actual response times + live CPMs |
| 2 | **Per-bidder floor override** | Floor min/max are global today; AdOps may want a per-SSP floor |

### Medium-term
| # | Feature | Why |
|---|---|---|
| 3 | **Banner tag generator tab** | Many publishers need both video + display; bidder catalog is already set up |
| 4 | **Companion banner rendering** — parse VAST companions and render to sidebar div | Same bid monetises two slots |

### Longer-term
| # | Feature | Why |
|---|---|---|
| 7 | **GAM line item setup wizard** | Walk AdOps through key-values → line item → creative in-dashboard |
| 8 | **Publisher onboarding flow** | Guided "Install → Configure → Verify" self-serve wizard |
| 9 | **Per-bidder per-format placement IDs** | IncrementX uses different IDs per banner size |

---

## 12. Test / Verification Scripts

Located in `/tmp/auction-test/` (throwaway, not committed):

| Script | What it checks |
|---|---|
| `verify-ui-local.js` | 22-check Production UI regression (sections, toggles, generated tag) |
| `verify-sandbox-local.js` | 20-check Sandbox multi-bidder simulation |
| `verify-bias-local.js` | 13-check Production bias toggle (ON/OFF/back ON paths) |
| `verify-sandbox-bias.js` | 7-check Sandbox bias toggle OFF path |

All use Puppeteer against `file://` URL of `index.html`.
Chrome binary: `/Users/aryanvani/.cache/puppeteer/chrome/mac_arm-138.0.7204.92/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`

**Test regex patterns** — use `[:\s]+` not `\s+` when matching log lines, because the phase logger uses `key: value` format with Unicode tree characters.

---

## 13. Architecture Notes

### Why `BIDDER_CATALOG` is at script scope
Originally inside the Production IIFE. Moved to script scope in v2.1.1 so both the Production and Sandbox pickers can share the same catalog and picker functions (`renderBidderPicker`, `readBidders`) without polluting `window`.

### Version Drift Check
`version-check.yml` greps `index.html` and `demo/publisher-test.html` for jsDelivr URLs and asserts they all contain `@v<VERSION>/`. Always update `VERSION` file when bumping CDN URLs.

### jsDelivr Immutability
Tagged releases (`@vX.Y.Z`) are cached for 1 year by jsDelivr CDNs. `@main` has ~12h cache. **Never tell publishers to use `@main` in production.**

### Prebid Bundle Build
The bundle is built via GitHub Actions (`build-prebid-bundle.yml`, manual dispatch). It clones Prebid.js source at the specified git tag, runs `gulp build --modules=<list>`, and commits the output back to `prebid/prebid-custom.js`. The workflow automatically appends consent modules.

---

## 14. Common Gotchas

1. **Bias = zero must be `"0.00"` string** — empty `data-bias` or missing attribute reverts to 0.10 default
2. **CSS specificity on inline labels** — always use `.adops-field label.adops-inline-label` not just `.adops-inline-label`
3. **VERSION file** — always bump it alongside the `@vX.Y.Z` URL changes; CI will catch drift but it's cleaner to do both in the same commit
4. **Prebid bundle bot commit** — after triggering `build-prebid-bundle.yml`, wait for the bot commit and `git pull` before pushing your own changes (avoid diverged history)
5. **Sequential Puppeteer tests** — don't run two browser sessions back-to-back in the same script; the second IMA init can timeout. Run as separate node processes.
6. **IncrementX params** — only `placementId` is needed (not publisherId). Banner and video use separate placement IDs; confirm with SSP account team.

---

*Last updated: v2.4.0 — 2026-06-02*
