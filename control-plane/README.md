# Bidding Player — Control Plane

The backend for the *Bidding Player* video header-bidding product. It does three
things:

1. **Stores who our publishers are** — a tenant hierarchy of
   `Account → Publisher → Site → AdUnit → Placement`, plus a demand-partner
   catalog and per-publisher enablement.
2. **Serves each player its config at runtime by id** — `GET /v1/config/{placement_id}`
   returns the assembled, engine-consumable config (mirroring the existing
   `loader.js` + `channel.json` fetch pattern: by id, short timeout, cacheable,
   with an engine-side last-known-good fallback).
3. **Receives and stores telemetry** — `POST /e` ingests player events
   (load, bid request, per-bidder response, win, impression, complete, error).

This is **Phases 0–1** only. Out of scope for now: self-serve sign-up, billing,
dynamic per-publisher Prebid bundles, GAM reporting join (Phase 2), reporting
dashboards, ML/dynamic floors. The data model is tenant-shaped so multi-account
and self-serve can be added later without a rewrite.

> The existing product (engine `player.js`, `loader.js`, Prebid bundle, tag
> generator) lives in a separate repo, `shashwatsilverpush/bidding-player`, and is
> **not** modified here. Engine changes needed to talk to this control plane are
> specified in [`docs/engine-instrumentation.md`](docs/engine-instrumentation.md).

## Stack

FastAPI + uvicorn · Pydantic v2 · SQLAlchemy 2.0 (async) + asyncpg · Alembic ·
PostgreSQL 15 · PyJWT + passlib[bcrypt] · pytest/httpx · ruff + mypy.

## Quick start (Docker)

```bash
cp .env.example .env          # edit secrets for anything real
docker compose up --build     # brings up Postgres + API, runs migrations
# API on http://localhost:8000  (docs at /docs)
```

The `api` container runs `alembic upgrade head` on boot, so the schema + the
6-partner demand seed + the bootstrap account are present immediately.

## Quick start (local, without Docker)

```bash
uv venv && source .venv/bin/activate      # or: python -m venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"                # or: pip install -e ".[dev]"
# Postgres must be reachable at DATABASE_URL (docker compose up db works):
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

## Auth

Single internal admin. `POST /auth/login` with `{username, password}` returns a
JWT; send it as `Authorization: Bearer <token>` to admin routes.

- Set `ADMIN_PASSWORD_HASH` (a bcrypt hash) in production. Generate one:
  ```bash
  python -m app.auth.security "your-password"
  ```
- For local dev you may set `ADMIN_PASSWORD` (plaintext); the app hashes it at
  startup and logs a warning. `ADMIN_PASSWORD_HASH` wins if both are set.

**Public routes** (called by anonymous browsers, CORS `*`): `GET /v1/config/{id}`
and `POST /e`. **Admin routes** (`/v1/admin/*`, `/auth/*`) are locked to
`ADMIN_CORS_ORIGINS`.

## Try it end to end

```bash
TOKEN=$(curl -s localhost:8000/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# create publisher -> site -> ad unit -> placement
PUB=$(curl -s localhost:8000/v1/admin/publishers -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"name":"Acme"}' | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')
# ... (see tests/helpers.py for the full chain) ...

# fetch the runtime config a player would use
curl -s localhost:8000/v1/config/<placement_id>

# send a telemetry event
curl -s -X POST localhost:8000/e -H 'content-type: application/json' \
  -d '{"v":1,"event":"player_load","eventId":"abc","account":"acc_root","placementId":"<id>","props":{}}'

# check the pipeline
curl -s "localhost:8000/v1/admin/stats" -H "authorization: Bearer $TOKEN"
```

## Tests

```bash
docker compose up -d db          # tests need Postgres (JSONB/NUMERIC)
pytest                           # DATABASE_URL / TEST_DATABASE_URL selects the DB
ruff check . && ruff format --check . && mypy app
```

Tests bootstrap the schema via `Base.metadata.create_all` for isolation/speed;
**migrations remain the canonical schema** and CI additionally runs
`alembic upgrade head` against a fresh DB to validate them.

## Architecture decisions

- **Events in Postgres for now, columnar later.** At ~10 publishers, volume is
  trivial and one datastore keeps ops simple. The `events` table is deliberately
  flat, append-only, and typed (promoted columns + `props JSONB`) so it can be
  mirrored 1:1 into ClickHouse/BigQuery in Phase 2 without reshaping. No columnar
  store is added yet.
- **Config by id, engine-side fallback.** The config endpoint is cacheable
  (`Cache-Control: public, max-age=300`) and the engine fetches it with a short
  timeout and falls back to inline `data-*` / last-known-good — a control-plane
  outage must never blank a publisher page.
- **Record raw AND biased CPM.** The engine inflates `hb_pb` via a floor bias, so
  `auction_win` stores both `cpm_raw` and `cpm_biased`; reporting can't silently
  overstate yield.
- **Tenant-shaped, single login.** Accounts/publishers are real rows; only the
  internal admin authenticates today.

## Runtime contracts

- **Config:** `GET /v1/config/{placement_id}` → `RuntimeConfig`
  (`app/schemas/config.py`). 404 for unknown/inactive placement.
- **Collector:** `POST /e` → `204`. Envelope + per-type props in
  [`docs/event-schema.md`](docs/event-schema.md). Idempotent on `eventId`.

## Layout

See [`CLAUDE.md`](CLAUDE.md) for the full map, conventions, and the Phase 2+
backlog — start there before extending the project.
