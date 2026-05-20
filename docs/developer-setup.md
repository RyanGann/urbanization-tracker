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
```

After ingestion, the API serves processed artifacts from `data/processed/`, source health from `/api/source-health`, agenda source documents from `/api/source-documents`, and reviewer-gated candidates from `/api/reviewer/staged-records`.

Inspect configured jurisdictions and connector health:

```bash
curl http://localhost:8000/api/jurisdictions
curl http://localhost:8000/api/connector-health
```

Move Phase 3 operational artifacts into Postgres when preparing a durable environment:

```bash
make db-migrate
make migrate-phase3-postgres
```

If you are using the Docker Compose database and API service, run:

```bash
docker compose exec api alembic upgrade head
make docker-migrate-phase3-postgres
```

Set `PHASE3_STORE_BACKEND=postgres` for the API and ingestion jobs after migration. Leave it as
`artifact` for local JSON-file development.

## Phase 1 Data Boundaries

- Seed development records are representative demo records, not live Huntsville source records.
- Seed environmental overlays are simplified fixtures for UI and data-shape validation.
- Permit point records should be labeled as low geometry confidence because they are not footprints.
- Public source links, source agency, review status, geometry source, and confidence labels are part of the MVP data contract.

## Phase 2 Data Boundaries

- `data/` contains live fetched source artifacts and is ignored by git.
- New Subdivisions polygons are treated as publishable public records with source attribution.
- Building Permits are point context with low geometry confidence, not footprints.
- Proximity flags are screening-level context and should not be treated as legal or environmental determinations.

## Phase 3 Data Boundaries

- Planning Commission agenda PDFs are public meeting documents, but parsed records are reviewer-gated.
- Agenda geometries default to low-confidence review points until a reviewer draws or matches a reliable geometry.
- Public submissions are low-confidence staged records until a reviewer validates the source and duplicate risk.
- Watch-area alerts are queued as email-channel records; SMTP delivery is a later operational integration.
- `PHASE3_STORE_BACKEND=postgres` stores source documents, staged agenda/submission records,
  published reviewer records, watch areas, alerts, record versions, and change-log entries in
  Postgres instead of `data/processed/phase3_*.json`.
- Set `REVIEWER_API_TOKEN` to require a bearer token for `/api/reviewer/*`; when it is unset,
  reviewer routes stay open for local development.

## Phase 4 Expansion Boundaries

- Jurisdiction/source configs live in `apps/api/app/jurisdictions/`.
- The Madison County config is a demo second-pilot fixture, not a live public data source.
- New sources must complete `docs/privacy-safety-checklist.md` before public display.
- Reviewer decision import/export is a local operational handoff, not a replacement for database audit tables.
