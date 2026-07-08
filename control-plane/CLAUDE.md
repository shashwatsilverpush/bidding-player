# CLAUDE.md — Control Plane Project Memory

> **Read this first before making changes.** This file is the authoritative
> context for AI agents (Claude Code) continuing this project. Update it whenever
> you finish a phase or change architecture. It replaces scrolling chat history.

---

## 1. What this repo is

The **control plane** (backend + admin dashboard) for *Bidding Player*, a video
header-bidding player. **Monorepo layout:** the engine (`player.js`, `loader.js`,
Prebid bundle, the original in-browser tag generator `index.html`) lives at the
**repo root**; this backend lives under **`control-plane/`**. The engine is served
to publishers via jsDelivr from the repo root, so its paths are unchanged.
**Don't modify the engine from here** — engine-side changes are written up as a
spec in `docs/engine-instrumentation.md` to be applied to the root `player.js`.

This backend delivers:
1. Store publishers + demand config (tenant hierarchy + demand catalog).
2. Serve runtime config by placement id (`GET /v1/config/{id}`).
3. Ingest telemetry (`POST /e`) into Postgres.
4. Generate the publisher embed `<script>` from DB config (`.../embed`) — a
   server-side port of the root `index.html::buildEngineFile`.
5. Analytics read APIs (`/v1/admin/analytics/*`) + a dev demo-data seeder.
6. A single-page **admin dashboard** at `/admin` (`app/static/admin.html`):
   Publishers · Properties · Demand · Player Tag · GAM · Analytics.

> **Engine wiring status:** the engine is NOT yet instrumented, so analytics
> populate only via the dev seeder (`POST /v1/admin/analytics/dev/seed`) or once
> `docs/engine-instrumentation.md` is applied. Generated tags are "baked" and work
> with the current engine today.

## 2. Stack & conventions

- **Python 3.12**, **FastAPI** + **uvicorn**, **Pydantic v2** for all I/O schemas.
- **PostgreSQL 15**, **SQLAlchemy 2.0 async** (typed `Mapped[...]` models) +
  **asyncpg**, **Alembic** migrations. **Migrations are the schema source of
  truth — never `create_all` in app code** (tests do it only for fixture speed).
- **Auth:** single internal admin, `POST /auth/login` → JWT (PyJWT), bearer on
  admin routes. Passwords via `passlib[bcrypt]`.
- **Env-only config** via `pydantic-settings` (`app/settings.py`); secrets never
  committed; see `.env.example`.
- **Lint/type:** `ruff` (lint+format) and `mypy` must stay green. Run
  `ruff check . && mypy app && pytest` before committing.
- IDs are opaque strings: `<prefix>_<random>` via `app.db.gen_id` (`acc_`, `pub_`,
  `site_`, `au_`, `plc_`, `dp_`, `pd_`, `evt_`, `aud_` audit rows, `req_` request ids).

## 3. Layout

```
app/
  main.py            # app + per-route CORS + router wiring + / -> /admin + /admin (static) + /health
  settings.py        # pydantic-settings (env)
  db.py              # async engine/session, Base, gen_id(), utcnow()
  static/admin.html  # single-page admin dashboard (6 tabs)
  models/            # SQLAlchemy: tenancy.py, demand.py, events.py, audit.py
  schemas/           # Pydantic: config.py (PlacementConfig/RuntimeConfig), admin.py, events.py
  auth/              # security.py (hash/jwt), deps.py (require_admin + audit context)
  routers/           # auth, admin_publishers, admin_demand, admin_audit, tags, analytics, config, collector, stats
  services/          # config_assembly, ingest, embed (buildEngineFile port), analytics, demo, seed, audit
migrations/          # alembic (async env.py); versions/ holds schema + seed
tests/               # pytest + httpx.AsyncClient; conftest bootstraps schema+seed
docs/                # event-schema.md, engine-instrumentation.md (Workstream B)
```

## 4. Data model (see `app/models/`)

`Account → Publisher → Site → AdUnit → Placement`.
`DemandPartner` (catalog, seeded with the 6 SSPs) and `PublisherDemand`
(per-publisher enablement + params + floor, `UNIQUE(publisher_id, demand_partner_id)`).
`Event` (append-only telemetry; flat + typed + `props JSONB`; promoted win cols
`cpm_raw`/`cpm_biased`/`hb_pb`/`bidder`).
`AuditLog` (append-only admin change history — see §5b).

Bootstrap account id is fixed: `acc_root` (`app/services/seed.py`). Publisher
creation defaults to it.

**Deletes are soft** for the tenant chain: `Publisher/Site/AdUnit/Placement` carry a
nullable `deleted_at`. Delete = stamp `deleted_at`; lists, `_get_or_404`, and config
assembly all filter `deleted_at IS NULL` (a deleted placement or any deleted ancestor
stops serving config, even for admin tag generation). Deleting a parent with live
children needs `?cascade=true` (else 409); cascade soft-deletes the subtree in one
transaction. `POST .../{id}/restore` clears `deleted_at` (children stay deleted).
`DemandPartner`/`PublisherDemand` are still hard-deleted; deleting a `DemandPartner`
still enabled anywhere → 409. Dashboard exposes delete (with cascade confirm) on
Properties/placements and a **History** tab over the audit log.

## 5. The two runtime contracts (keep stable under `/v1/`)

- **Config:** `GET /v1/config/{placement_id}` → `RuntimeConfig`. Assembles
  placement config + enabled `PublisherDemand` bidders. Precedence:
  publisher_demand defines the set + default params/floor; `config.enabledBidders`
  restricts; `config.bidderOverrides` merges on top (placement wins). 404 if
  unknown/inactive/paused-publisher. Sets `Cache-Control: public, max-age=300`.
- **Collector:** `POST /e` → always `204`. Validates a discriminated-union
  envelope (`app/schemas/events.py`), drops unknown accounts / invalid events
  silently, dedups on `eventId`, enriches (ts_server, UA, ip_country stub),
  applies the consent rule, promotes win CPMs. Tolerates `text/plain` bodies.

## 5b. Admin change history (audit log)

`GET /v1/admin/audit-log` (admin auth) returns entries newest-first with filters
`entity_type`/`entity_id`/`actor`/`action`/`since`/`until` + `limit`/`offset`. Each row
is Action / entity id / Time / actor + device signals (`ip`, `user_agent`, `method`,
`path`, `request_id`) + `before`/`after`/`changed_fields`. Surfaced in the dashboard's
**History** tab.

Capture is automatic in `app/services/audit.py` via SQLAlchemy session listeners —
**no router writes to it directly**:
- `before_flush` records updates + deletes (attribute *history* is only reliable
  here); `after_flush` records inserts (PKs assigned) and writes the whole batch with
  one core `INSERT` on the open transaction. `before_commit` is **not** usable — it
  fires *before* the commit's flush.
- Only `_AUDITED_TABLES` (tenant chain + demand) are tracked; `Event` and `audit_log`
  are excluded (the latter would loop).
- A soft delete (UPDATE of `deleted_at`) is logged as `delete`/`restore`, not `update`.
- Actor + device signals come from a `ContextVar` set in `require_admin`, which is
  **`async`** on purpose: a sync dep runs in a threadpool whose ContextVar writes
  wouldn't reach the flush. Single admin today, so `actor` is usually `"admin"`; `ip`
  (X-Forwarded-For first hop, else socket peer) is a device hint, not identity.

## 6. Critical domain facts (don't regress)

- **Raw vs biased CPM:** the engine adds a floor bias and inflates the `hb_pb`
  sent to GAM. `auction_win` MUST carry both `cpmRaw` and `cpmBiased`; they are
  stored in separate columns. Never collapse them.
- **`bias` is a string** ("0.00" = explicit zero) because the engine treats
  empty/absent as its 0.10 default.
- **Fail safe:** config endpoint is cacheable + the engine has a fallback; nothing
  here should assume the control plane is always up from the browser's side.
- **The 6 demand partners** mirror the engine's `BIDDER_CATALOG`. The canonical
  list is `app/services/seed.py::DEMAND_PARTNERS`; the seed migration inlines the
  same rows (keep in sync if you add a partner).

## 7. How to run / test

```bash
docker compose up --build         # Postgres + API + migrations
pytest                            # needs Postgres (docker compose up -d db)
ruff check . && ruff format --check . && mypy app
alembic revision --autogenerate -m "msg"   # after model changes
alembic upgrade head
```

CI (`.github/workflows/ci.yml`) runs ruff + mypy + pytest against a Postgres
service, and separately runs `alembic upgrade head` on a fresh DB to validate
migrations.

## 8. Phase 2+ backlog (not built yet — pick up here)

Priority order:
1. **GAM reporting join** — pull GAM Ad Manager API delivery/revenue and reconcile
   with client-side `auction_win`/`impression` so eCPM is real, not bid-side only.
   This is the single most valuable next step for "increase yield."
2. **Columnar mirror** — stream `events` to ClickHouse/BigQuery (the table is
   already shaped for a 1:1 copy) once volume or query needs grow.
3. **Reporting UI / API** — per-publisher/partner/ad-unit dashboards over events.
4. **Onboarding flow + live verification** — detect the tag is live, ads.txt has
   our seller line, GAM line items exist. (See gap analysis: verification is the
   hard, valuable part.)
5. **GAM line-item setup wizard** — automate price-priority line items +
   `hb_pb`/`hb_bidder` creatives via the GAM API.
6. **Self-serve + publisher logins** — the model is already tenant-shaped; add
   real accounts, roles, and per-tenant auth.
7. **Per-bidder floors / per-placement demand tuning** — schema already supports
   `PublisherDemand.floor` and `config.bidderOverrides`; expose in UI.
8. **Dynamic Prebid bundles** — per-publisher adapter sets instead of the
   monolithic bundle.
9. **ads.txt / sellers.json / schain + identity modules** — supply-chain plumbing
   the engine/wrapper needs for demand to buy.

## 9. Gotchas

- Set env vars **before** importing the app in tests — `get_settings()` is
  `lru_cache`d (`tests/conftest.py` does this at module top).
- CORS is a **custom per-path middleware** in `main.py` (public routes `*`, admin
  routes allowlisted) because one global `CORSMiddleware` can't express both.
- The collector returns 204 even on drop (unknown account / bad event) so it never
  leaks which accounts exist and never blocks the page.
- Alembic `env.py` is async and pulls `DATABASE_URL` from settings — don't rely on
  `sqlalchemy.url` in `alembic.ini`.
