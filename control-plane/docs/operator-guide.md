# Operator Guide — Bidding Player Control Plane

A step-by-step for any internal user to run the tool end to end: add a publisher →
configure demand + ad server → generate the player tag → test it → share it →
watch analytics.

> Terms: **Prebid** = the header-bidding demand (SSPs that bid). **GAM** = Google
> Ad Manager, your ad server that the winning price is passed to. A **placement**
> is one ad slot on one ad unit, and is what a generated tag maps to.

---

## 0. Access & sign in
1. Open the dashboard: `https://<your-control-plane-domain>/admin`
   (locally: `http://localhost:8000/admin`).
2. Sign in with your admin **username / password**.
3. Top nav: **Publishers** · **Demand Partners** · **Analytics**.

*Tip: if the page looks out of date after a deploy, hard-refresh (Cmd/Ctrl+Shift+R).*

---

## 1. Add a publisher
1. **Publishers** tab → **+ New publisher**.
2. Enter **Name** and (optional) **GAM network code** (e.g. `21775744923`).
3. **Create** → you land inside the publisher.

## 2. Add a property (site)
1. In the publisher → **Properties** tab → **+ New site**.
2. Enter the **Domain** (e.g. `publisher.com`). **Add site** → click it to open.

## 3. Add an ad unit
1. In the site → **+ New ad unit**.
2. **GAM ad unit path** (e.g. `/21775744923/publisher/video`) + **Format** (video/banner).
3. **Add ad unit** → click it to open.

## 4. Add a placement
1. In the ad unit → **+ New placement**.
2. **Name**, **Type** (instream / outstream), **Engine delivery** (auto-update recommended).
3. **Create** → opens the placement on the **① Prebid — demand** tab.

---

## 5. Enable demand partners (Prebid) — publisher level
Bidders are shared across a publisher's placements, so they're set once per publisher.
1. Go to the publisher → **Demand** tab.
2. For each SSP you use → **Enable** → fill its **required params** (real seat /
   placement / publisher IDs from your SSP account) + optional **floor** → **Save**.
3. To add an SSP that isn't listed: top nav **Demand Partners** → **+ Add partner**
   (also requires that adapter in the Prebid bundle — see §12).

## 6. Configure the Prebid side — placement → ① Prebid — demand
- Left card shows the **enabled SSPs** for this publisher (manage them in the Demand tab).
- **Auction settings** (Save when done):
  - **Bidder timeout (ms)** — how long to wait for bids (e.g. 1200).
  - **Floor bias ($)** — added to the winning CPM before bucketing into `hb_pb`.
  - **Floor min / max ($)** — reject bids below min; cap at max (optional).
  - **Prebid cache URL** — where the winning VAST is cached (default is fine).

## 7. Configure the GAM side — placement → ② GAM — ad server
1. **GAM VAST tag URL** — the publisher's real GAM ad request
   (`…/gampad/ads?iu=/NETWORK/ad_unit&…&output=vast&…`). **Save GAM tag**.
2. The **key-values** table shows what to target in GAM: `hb_pb`, `hb_bidder`
   (+ per-bidder variants). **You must create matching price-priority line items +
   a VAST creative in GAM** for header-bid demand to actually win (see §12).

---

## 8. Generate the player tag — placement → Player Tag
1. Set **Engine delivery** (auto-update), **content video URL** (instream), **div id**,
   and player behaviour (autoplay / muted / fluid / loop / sticky).
2. **Save & regenerate** → the embed `<script>` appears on the right.

## 9. Preflight check
- Click **✓ Preflight check** → confirms GAM tag set + valid URL, ≥1 demand partner,
  instream video present, div id + prebid bundle present. Fix any ⚠️ before sharing.

## 10. Test it — **▶ Test in browser**
- Opens a preview page that embeds the exact tag and shows a live inspector:
  - **Player events** (from the engine): `player_load → bid_request → bid_response →
    auction_win → GAM request → impression → complete`.
  - **Auctions**, **Key-values sent to GAM**, **Network calls**.
- Add `?debug=true` (already on) to see engine STEP/WINNER logs in the browser console.
- **Reality check:** from the dashboard origin, SSPs usually **no-bid** (the domain
  isn't allow-listed) and GAM serves a sample/house ad. That's expected — the preview
  proves the tag *loads, fires requests, and calls GAM*. Real bids need the tag on the
  **publisher's own allow-listed domain** (§12).

## 11. Share the tag
- **Copy tag** → paste the `<script>` into the publisher's page where the ad should render.

---

## 12. What must be set up OUTSIDE the tool (so it actually earns)
The dashboard generates a correct tag, but a publisher only monetizes once:
1. **SSP allow-listing** — real IDs + the publisher's domain registered with each SSP.
2. **`ads.txt`** on the domain listing authorized sellers.
3. **GAM line items** — price-priority line items keyed on `hb_pb`/`hb_bidder` + a VAST
   creative (`hb_uuid` macro). Without these, only the house/direct ad serves.
4. **Consent/CMP** for EU traffic (engine defaults to non-EU).
5. **New SSP adapter** → the served Prebid bundle must include it (rebuild required).

## 13. View analytics
- **Analytics** (top nav) — account-wide KPIs, funnel, daily wins and a **Report** table.
  - **Range** — Today, Yesterday, Last 7 / 30 days, This month, Last month, All time or a
    custom date range. Dates and day rows follow the chosen **Timezone** — pick the
    publisher's own (e.g. `Europe/Prague`) when reconciling against their GAM report.
  - **Filters** — publisher → site → ad unit → placement (each list only offers children of
    the level above), format, player type (instream/outstream), country, device
    (desktop / mobile / tablet / CTV, from the User-Agent). KPIs, funnel, chart and report
    all respect the same filters.
  - **Report** — *Rows by* + optional *then by* any of: day, week, month, hour, publisher,
    site, ad unit, placement, format, player type, country, device, engine version,
    initial vs refresh. Presets: **Day-wise**, **Publisher × day**, **Site × day**. Click a
    column header to sort; click a publisher/site/ad-unit name to drill one level down.
    A **Total** row sits at the bottom; **Export CSV** downloads every metric (up to 10k rows).
- Per placement: the placement's **Analytics** tab (that placement only), including a
  **Day-wise** table that can be split by device, country, refresh or engine version.
- **Every metric is labelled by who produced it** — KPI tiles, funnel and report columns are
  grouped into **Page**, **Header bidding (Prebid)** and **Ad server (GAM)**. The report's
  *Columns* switch shows All / Header bidding / Ad server (GAM).
  - *Page* — loads, View % (**—** = not measured: only `data-lazy` tags report
    viewability), ads per load.
  - *Header bidding* — bid requests, **No-bid %** (no usable bid, incl. under floor-min),
    wins, win rate, **HB impressions** (impressions on opportunities HB won — an upper
    bound, GAM may still serve a higher-priority line item), HB share, avg bid (raw) and
    bid sent to GAM (biased), **HB revenue** (raw winning CPMs ÷ 1000 for rendered wins),
    **HB eCPM** (per HB impression), **HB RPM** (per 1000 loads).
  - *Ad server (GAM)* — ad requests, impressions (all demand), **GAM fill**, **Unfilled %**,
    **Error %** (per ad request), completion.
  - **GAM revenue / GAM eCPM are shown as "not connected"**: IMA exposes no price, so
    AdX / direct / house revenue is only in GAM's own report until the GAM reporting join
    (backlog #1) exists. Never compare HB revenue against GAM total revenue.
- **Ad errors — why ads didn't fill**: IMA errors grouped by cause with the top IMA codes,
  plus a per-day pivot. *No ad returned* (1009/303) and *Invalid VAST* are **GAM** side;
  *Request blocked / timed out* (301/302/1005/1012) is **network**; *Creative failed to
  play* (400–405, 901, …) is **player / creative** side.
- **Header-bidding partners**: per-SSP bids, no-bids, timeouts, errors, CPM, latency, wins
  — on the top-level page (respects filters) and on each placement.
- **Reconciling with GAM** — expect our *ad requests* to run ~10–20% above GAM's (ad
  blockers / closed pages stop calls before they reach GAM); *impressions* should match
  within a few %. Set the dashboard **Timezone** to the GAM network's, or daily rows shift.
  The chosen timezone and column view are remembered in your browser.
- **Country** comes from the CDN/edge header in front of the collector (`CF-IPCountry`,
  `CloudFront-Viewer-Country`, `X-Vercel-IP-Country`, …). With no such proxy every row
  reads `unknown`.
- API: `GET /v1/admin/analytics/report?dimensions=publisher,day&tz=…&date_from=…&date_to=…`
  (+ any filter, `sort`, `order`, `limit`); `/report.csv` for the same as CSV;
  `/errors?by_day=true` for the error breakdown;
  `/filters` for the filter options. Summary/timeseries/bidders accept the same filters.
- **Demo data (dev/staging only):** a placement's Analytics tab has a **Generate**
  button to insert synthetic events so the dashboards have data before real traffic.
  Disabled in production (`ALLOW_DEV_ENDPOINTS=false`).

## 14. Troubleshooting
| Symptom | Cause / fix |
|---|---|
| Only a **sample/test ad** plays | GAM tag is the `single_ad_samples` demo unit, and/or no real bids off-domain, and/or no GAM line items. Use the real GAM tag + set up line items + test on the real domain. |
| **No bids** come back | SSP params not real, or domain not allow-listed / no `ads.txt`. |
| **Analytics empty** | No traffic yet — run "Test in browser" or generate demo data (non-prod). |
| **Dashboard looks stale** after deploy | Hard-refresh (Cmd/Ctrl+Shift+R). |
| **Engine tag 404** | The engine version isn't released to jsDelivr / repo not public. |
