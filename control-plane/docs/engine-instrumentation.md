# Workstream B — Engine Instrumentation Plan

> **This describes changes to `engine/player.js` in the separate
> `shashwatsilverpush/bidding-player` repo.** It is a spec + example code for the
> engine team, not something built in the control-plane repo. Line numbers are
> approximate against **v2.5.0** — confirm before editing.

The engine gains two capabilities:
1. **Runtime config fetch** — resolve config by `placementId` from the control
   plane instead of reading everything off the tag (backward compatible).
2. **Telemetry beacons** — emit the events in `docs/event-schema.md` at each
   lifecycle moment, fire-and-forget, never blocking the auction/render path.

Both must degrade safely: a down control plane must never blank a publisher page.

---

## 1. Identity & runtime config on the tag (backward compatible)

Add three optional attributes, mirroring the existing loader pattern
(`loader.js` fetches a manifest with a **1.5s timeout** + baked fallback):

```html
<script src=".../engine/player.js" id="adtech-player-core"
        data-account="acc_root"
        data-placement-id="plc_5A3bK9xQ2m"
        data-config-url="https://cp.example.com/v1/config/__PLACEMENT__"
        ...existing data-* still allowed as fallback...></script>
```

Bootstrap change (near the top of the IIFE, after `cfg` is read ~line 58):

```js
function loadRuntimeConfig(cb) {
  var pid = currentScript.getAttribute("data-placement-id");
  var url = currentScript.getAttribute("data-config-url");
  if (!pid || !url || typeof fetch === "undefined") return cb(null); // legacy path
  url = url.split("__PLACEMENT__").join(encodeURIComponent(pid));

  var done = false;
  var t = setTimeout(function () { if (!done) { done = true; cb(null); } }, 1500);
  try {
    fetch(url, { credentials: "omit" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (remote) { if (!done) { done = true; clearTimeout(t); cb(remote); } })
      .catch(function () { if (!done) { done = true; clearTimeout(t); cb(null); } });
  } catch (e) { if (!done) { done = true; clearTimeout(t); cb(null); } }
}
```

`cb(remote)` merges the returned JSON over `cfg` (remote wins for
`timeout`, `bias`, `floorMin/Max`, `bidders`, `prebidUrl`, `video`, `sticky`,
plus `beaconUrl`, `sampleRate`, `account`). On `null` (timeout/error/legacy tag)
the engine uses the inline `data-*` config exactly as today — **page never goes
dark**. Wrap the existing `ready(...)` bootstrap so the auction only starts
inside `cb`.

The RuntimeConfig JSON shape is defined by `GET /v1/config/{placement_id}` (see
that endpoint / `app/schemas/config.py`).

---

## 2. Beacon transport (must never throw into the auction)

```js
var TELE = {
  url: null,          // set from resolved config.beaconUrl
  ctx: {},            // { account, placementId, adUnitPath, engineVersion, sessionId }
  sample: 1.0,        // config.sampleRate
  on: false,
};

function sid() { /* random per-pageview id, e.g. Date.now()+"-"+Math.random() */ }

function beacon(event, props) {
  try {
    if (!TELE.on || !TELE.url) return;
    if (TELE.sample < 1 && Math.random() > TELE.sample) return;
    var body = JSON.stringify({
      v: 1, event: event, ts: Date.now(), eventId: uuid(),
      account: TELE.ctx.account, placementId: TELE.ctx.placementId,
      adUnitPath: TELE.ctx.adUnitPath, pageUrl: location.href,
      sessionId: TELE.ctx.sessionId, engineVersion: TELE.ctx.engineVersion,
      consent: readPrebidConsent(), props: props || {}
    });
    var blob = new Blob([body], { type: "text/plain" }); // text/plain => no CORS preflight
    if (navigator.sendBeacon && navigator.sendBeacon(TELE.url, blob)) return;
    fetch(TELE.url, { method: "POST", body: body, keepalive: true, credentials: "omit" });
  } catch (e) { /* telemetry must never break playback */ }
}
```

- **`sendBeacon` first**, `fetch(..., {keepalive:true})` fallback. Both wrapped in
  `try/catch`.
- **`text/plain`** avoids a CORS preflight; the collector reads the raw body.
- **Consent:** reuse Prebid's already-resolved TCF/USP/GPP consent
  (`pbjs.getConsentMetadata()` / the consent module state) — do **not** resolve
  consent a second time for telemetry.
- **Sampling:** honor `sampleRate` from config.

---

## 3. Hook map (approx. v2.5.0 line refs)

The engine already centralizes logging in `step`, `winLog`, `noBidLog`
(`?debug=true`). Route beacons through thin wrappers on those, plus add the two
listeners that don't exist yet (per-bidder response, IMA started).

| event | where | how |
|---|---|---|
| `player_load` | bootstrap / `ensureMount` (~184) | `beacon("player_load", {placement: cfg.placement, referrer: document.referrer, viewport: innerWidth+"x"+innerHeight})` after mount |
| `bid_request` | `runAuction` → `pbjs.requestBids` (~571) | `beacon("bid_request", {bidders: names, timeout: cfg.timeout})` |
| `bid_response` | **new** `pbjs.onEvent('bidResponse', …)` near ~573 | `beacon("bid_response", {bidder, cpm, currency, status, latencyMs})` — also listen to `noBid`, `bidTimeout`, `bidderError` for the non-`bid` statuses |
| `auction_win` | `bidsBackHandler` (~587–606) | `beacon("auction_win", {bidder: winner.bidder, cpmRaw: rawCpm, cpmBiased: finalCpm, hbPb: targeting.hb_pb, floorApplied})` — **emit both CPMs** |
| `impression` | IMA `CONTENT_PAUSE_REQUESTED` (~259 instream / ~365 outstream); **add** `AdEvent.Type.STARTED`/`IMPRESSION` | `beacon("impression", {adId, creativeId, adDuration})` |
| `ad_complete` | `ALL_ADS_COMPLETED` (~269) | `beacon("ad_complete", {viewedPct, quartiles})` |
| `ad_error` | `AD_ERROR` (~252 loader / ~254 manager) | `beacon("ad_error", {errorCode, phase, fallbackServed})` |
| `no_demand` | `noBidLog()` sites (~511/582/611) | `beacon("no_demand", {phase, fallbackServed:true})` |

Wire `TELE.on = true`, `TELE.url = config.beaconUrl`, `TELE.ctx`, `TELE.sample`
inside the runtime-config callback (§1) before the auction begins, so
`player_load` and everything after it are attributed.

---

## 4. Testing checklist for the engine team

- Legacy tag (no `data-placement-id`) behaves exactly as v2.5.0.
- Config fetch timeout (block the URL) still renders via inline `data-*`.
- Beacons fire for a full instream + outstream playthrough (`?debug=true` to
  cross-check against `step`/`winLog`).
- Throwing from `beacon()` (e.g. force `JSON.stringify` to fail) does not break
  playback.
- `auction_win` beacon carries `cpmRaw !== cpmBiased` when bias is on.
