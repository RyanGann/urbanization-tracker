# Developer Setup

Last updated: 2026-05-20

## Prerequisites

- Docker and Docker Compose.
- Python 3.12.
- Node.js 20 or newer.
- npm.

## One-Command Stack

```bash
docker compose up --build
```

Services:

- Web: http://localhost:5173
- API: http://localhost:8000
- API health: http://localhost:8000/health
- Postgres/PostGIS: localhost:5432
- Redis: internal Compose service at `redis:6379`

The API runs Alembic migrations at container startup. Phase 1 map and reviewer flows use seed/demo records from `apps/api/app/seed/seed_data.json`; live ingestion is intentionally deferred.

## Local Development

Install backend dependencies:

```bash
make install-api
```

Install frontend dependencies:

```bash
make install-web
```

Run the API:

```bash
make dev-api
```

Run the web app:

```bash
make dev-web
```

## Checks

Backend tests:

```bash
make test-api
```

Frontend unit tests:

```bash
make test-web
```

Type checks:

```bash
make typecheck
```

Build the frontend:

```bash
make build
```

Playwright E2E scaffold:

```bash
make e2e
```

Run Huntsville ingestion:

```bash
make ingest-huntsville
make ingest-huntsville-agendas
make ingest-madison-county
```

After ingestion, the API serves canonical processed records, source health from
`/api/source-health`, agenda source documents from `/api/source-documents`, and reviewer-gated
candidates from `/api/reviewer/staged-records`. Local development stores canonical processed output
under `data/processed/`; hosted environments can store the canonical processed collections in
Postgres with `PROCESSED_STORE_BACKEND=postgres`.
Raw GeoJSON, agenda PDFs, extracted text, and archive-page captures are indexed in
`data/processed/artifact_manifest.json`.

Inspect configured jurisdictions and connector health:

```bash
curl http://localhost:8000/api/jurisdictions
curl http://localhost:8000/api/connector-health
```

Move processed and Phase 3 operational artifacts into Postgres when preparing a durable
environment:

```bash
make db-migrate
make migrate-processed-postgres
make migrate-phase3-postgres
make processed-store-status
make phase3-store-status
```

If you are using the Docker Compose database and API service, run:

```bash
docker compose exec api alembic upgrade head
make docker-migrate-processed-postgres
make docker-migrate-phase3-postgres
```

Set `PROCESSED_STORE_BACKEND=postgres` and `PHASE3_STORE_BACKEND=postgres` for the API and
ingestion jobs after migration. Leave them as `artifact` for local JSON-file development. Hosted
environments should treat Postgres as the operational store for reviewer-facing Phase 3 data; raw
PDFs, raw GeoJSON payloads, and extracted text remain file artifacts until object storage is
configured.

## Phase 1 Data Boundaries

- Seed development records are representative demo records, not live Huntsville source records.
- Seed environmental overlays are simplified fixtures for UI and data-shape validation.
- Permit point records should be labeled as low geometry confidence because they are not footprints.
- Public source links, source agency, review status, geometry source, and confidence labels are part of the MVP data contract.

## Phase 2 Data Boundaries

- `data/` contains live fetched source artifacts and is ignored by git.
- `data/processed/artifact_manifest.json` tracks raw artifact size, hash, source key, local path,
  and storage URI. Set `ARTIFACT_STORAGE_BASE_URI` to test object-storage-style URI prefixes.
- `PROCESSED_STORE_BACKEND=postgres` stores canonical processed development records, staged
  records, environmental overlays, and source health in Postgres instead of
  `data/processed/*.json`.
- New Subdivisions polygons are treated as publishable public records with source attribution.
- Building Permits are point context with low geometry confidence, not footprints.
- Proximity flags are screening-level context and should not be treated as legal or environmental determinations.

## Phase 3 Data Boundaries

- Planning Commission agenda PDFs are public meeting documents, but parsed records are reviewer-gated.
- Agenda geometries default to low-confidence review points until a reviewer draws or matches a reliable geometry.
- Public submissions are low-confidence staged records until a reviewer validates the source and duplicate risk.
- Watch-area alerts are queued as email-channel records. SMTP delivery is disabled unless
  `ALERT_DELIVERY_ENABLED=true`, `SMTP_HOST`, and `SMTP_FROM_EMAIL` are configured.
- Run `make send-alerts` to process a bounded delivery batch. `ALERT_DELIVERY_RATE_LIMIT` controls
  the maximum alerts sent per run.
- Watch areas store the delivery address privately for outbound email and expose only
  `email_hash`/`email_hint` through reviewer APIs. Every watch area gets an unsubscribe token.
- `PHASE3_STORE_BACKEND=postgres` stores source documents, staged agenda/submission records,
  published reviewer records, watch areas, alerts, record versions, and change-log entries in
  Postgres instead of `data/processed/phase3_*.json`.
- `GET /api/reviewer/processed-store` and `make processed-store-status` report the canonical
  processed collection backend and migration state.
- `GET /api/reviewer/phase3-store` and `make phase3-store-status` report which Phase 3 collections
  are in artifacts, Postgres, or local test memory.
- Set `REVIEWER_API_TOKEN` to require a bearer token for `/api/reviewer/*`; when it is unset,
  reviewer routes stay open for local development.

## Phase 4 Expansion Boundaries

- Jurisdiction/source configs live in `apps/api/app/jurisdictions/`.
- The Madison County config includes a live recorded-subdivision source; the inactive demo fixture
  is retained only as an onboarding example.
- New sources must complete `docs/privacy-safety-checklist.md` before public display.
- Reviewer decision import/export is a local operational handoff, not a replacement for database audit tables.
