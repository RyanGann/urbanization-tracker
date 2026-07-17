# Deployment Plan

Last updated: 2026-05-20

## Product Stance

- Public users do not need accounts for the alpha. They can browse the map, filter records, open
  source links, submit a public source tip, and create a watch area without logging in.
- Email is used only as a watch-area alert contact. It is not a login identifier, payment identity,
  or profile system.
- Reviewer/admin access is separate from public use. Set `REVIEWER_API_TOKEN` in deployed
  environments and protect `/review` plus `/api/reviewer/*` at the edge.
- Do not build a supporter/pro account tier yet. If demand appears, start with shareable map URLs,
  browser-local saved filters, and a donation/support link before adding payments or accounts.

## Recommended Alpha Path

Use Render for the first public alpha:

- API: Docker web service from `apps/api/Dockerfile`.
- Web: static site from the Vite build in `apps/web`.
- Database: managed Postgres with the PostGIS extension enabled.
- Edge access: Cloudflare Access or equivalent email allowlist for `/review` and
  `/api/reviewer/*`.
- Email delivery: keep queued alerts internal until SMTP credentials and a scheduled delivery job
  are configured.

This keeps infrastructure small while avoiding a user-auth buildout.

## Render Setup Notes

The repository includes a starter [render.yaml](../render.yaml) Blueprint with:

- Docker API service.
- Static Vite frontend.
- Managed Render Postgres database.
- Cron jobs for Huntsville ArcGIS ingestion, Huntsville agenda PDF ingestion, Madison County
  ingestion, and bounded alert delivery.

The initial private alpha uses Render's generated URLs:

- Web: `https://urbanization-tracker-web.onrender.com`
- API: `https://urbanization-tracker-api.onrender.com`

The API, cron jobs, and Postgres database are placed in Render's Ohio region. The database uses the
paid `basic-1gb` plan and blocks public database connections; application services use its private
connection string. The static site uses the free plan.

Scheduled source ingestion is created with `HOSTED_INGESTION_ENABLED=false`. Leave it disabled until
raw payloads and PDFs are uploaded to durable object storage. Alert delivery also remains disabled.
These controls let the web/API/database deploy without silently losing audit artifacts from cron
containers.

The Blueprint uses the generated Render URLs for `VITE_API_BASE_URL`, `CORS_ORIGINS`, and
`PUBLIC_BASE_URL`. Update those values when custom domains are selected.

API service:

- Dockerfile path: `apps/api/Dockerfile`.
- Docker context: `apps/api`.
- Start command: use the Dockerfile default. It runs migrations and starts Uvicorn on
  `${PORT:-8000}`.
- Required environment variables:
  - `DATABASE_URL`: Render Postgres internal connection URL, using the SQLAlchemy driver prefix if
    needed.
  - `INGESTION_DATA_DIR`: `/app/data`.
  - `ARTIFACT_STORAGE_BASE_URI`: optional object-storage URI prefix used in artifact manifest
    entries when raw files are mirrored outside the API filesystem.
  - `CORS_ORIGINS`: production web origin.
  - `REVIEWER_API_TOKEN`: generated secret shared only with reviewers.
  - `PROCESSED_STORE_BACKEND`: `postgres`.
  - `PHASE3_STORE_BACKEND`: `postgres`.
  - `PUBLIC_BASE_URL`: production origin used in record and unsubscribe links.
  - `ALERT_DELIVERY_ENABLED`: `true` only after SMTP credentials are configured.
  - `ALERT_DELIVERY_RATE_LIMIT`: start conservatively, for example `25`.
  - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`,
    `SMTP_USE_TLS`: provider settings for outbound alerts.

Web static site:

- Build command from the repo root: `npm install && npm --workspace apps/web run build`.
- Publish directory: `apps/web/dist`.
- Required environment variable:
  - `VITE_API_BASE_URL`: deployed API origin, or an empty same-origin path if a reverse proxy maps
    `/api` to the API service.

Data persistence:

- The current API can read canonical processed ingestion collections from Postgres with
  `PROCESSED_STORE_BACKEND=postgres`; local artifact mode still reads `INGESTION_DATA_DIR`.
- Render service filesystems are ephemeral unless a persistent disk is attached.
- A disk can be attached to the API service at `/app/data`, but it cannot be shared with a Render
  cron job.
- Canonical processed collections can run from Postgres with `PROCESSED_STORE_BACKEND=postgres`.
  Before switching an existing environment, run `make db-migrate` and
  `make migrate-processed-postgres` from an environment that can reach the deployed database.
- Phase 3 operational collections can run from Postgres with `PHASE3_STORE_BACKEND=postgres`.
  Before switching an existing environment, run `make db-migrate` and
  `make migrate-phase3-postgres` from an environment that can reach the deployed database.
- Verify the canonical processed store with `make processed-store-status` or
  `GET /api/reviewer/processed-store`, and verify the Phase 3 store with
  `make phase3-store-status` or `GET /api/reviewer/phase3-store`. Both API routes require reviewer
  access when `REVIEWER_API_TOKEN` is configured. Any collection with
  `requires_migration=true` still has JSON artifacts that have not been copied into Postgres.
- Ingestion writes `data/processed/artifact_manifest.json` with hashes, sizes, source keys, and
  storage URIs for raw GeoJSON, agenda PDFs, extracted text, and archive-page captures.
- Bulk raw source artifacts, source PDFs, and generated map artifacts should still be mirrored to
  object storage before hosted automated ingestion is considered complete. Set
  `ARTIFACT_STORAGE_BASE_URI` to the object-storage prefix used for those mirrored paths.

Preflight:

- Before launch, run the production configuration check from an environment with the same secrets
  and database network access as the API:

  ```bash
  make deployment-preflight
  ```

- The command validates reviewer token protection, Phase 3 and canonical processed Postgres modes,
  deployed HTTPS CORS and public URL settings, alert delivery settings, PostgreSQL connectivity,
  and the PostGIS extension.
  Use `python -m app.ingestion.cli deployment-preflight --skip-database` only for config-only dry
  runs where the database is intentionally unreachable.

Hosted ingestion jobs:

| Job | Starter schedule | Command | Durable store |
| --- | --- | --- | --- |
| `urbanization-tracker-huntsville-ingestion` | `17 8 * * *` | `sh -c "alembic upgrade head && python -m app.ingestion.cli ingest-huntsville --data-dir /app/data"` | `processed_collection_items` |
| `urbanization-tracker-agenda-ingestion` | `43 9 * * 1-5` | `sh -c "alembic upgrade head && python -m app.ingestion.cli ingest-huntsville-agendas --data-dir /app/data --document-limit 3"` | `phase3_collection_items` |
| `urbanization-tracker-madison-county-ingestion` | `29 11 * * 1` | `sh -c "alembic upgrade head && python -m app.ingestion.cli ingest-madison-county --data-dir /app/data"` | `processed_collection_items` |
| `urbanization-tracker-alert-delivery` | `*/15 * * * *` | `sh -c "alembic upgrade head && python -m app.ingestion.cli send-alerts"` | `phase3_collection_items` |

These schedules are starter values intended to avoid top-of-hour bursts. Keep
`PROCESSED_STORE_BACKEND=postgres` and `PHASE3_STORE_BACKEND=postgres` on cron jobs so the useful
published/staged state survives across ephemeral cron containers. The raw PDFs, raw ArcGIS payloads,
and extracted text written under `/app/data` are still temporary unless a persistent disk or object
storage sink is added.

## Option Matrix

Render is the recommendation for the alpha because it gives managed services, Docker support, static
hosting, managed Postgres/PostGIS, TLS, and low operational load.

DigitalOcean App Platform is a reasonable second choice if predictable pricing and a broader cloud
console matter more than Render's simpler app setup.

Railway is excellent for fast iteration, but the project will need careful environment and cost
tracking once ingestion jobs and data storage grow.

Fly.io is strong for Docker and global placement, but it asks for more ops judgment than the alpha
needs.

A small VPS is cheapest long term, but it makes backups, reverse proxying, deploys, system updates,
and monitoring our responsibility from day one.

Supabase can be useful later for hosted Postgres, storage, and optional auth, but adopting Supabase
Auth now would add an account model before the product needs one.

## Deployment Blockers Before Public Launch

- Run `make deployment-preflight` against production-equivalent environment variables and resolve
  any failing checks.
- Set `REVIEWER_API_TOKEN` and verify private reviewer API routes return `401` without it.
- Put `/review` and `/api/reviewer/*` behind an edge access policy.
- Run `make migrate-processed-postgres` and `make migrate-phase3-postgres` before enabling hosted
  cron jobs against an existing artifact-backed environment.
- Decide whether the first public alpha enables scheduled ingestion immediately or starts from a
  manually reviewed database snapshot.
- Configure database backups and PostGIS.
- For manual database backups, run:

  ```bash
  DATABASE_URL=... make backup-db
  ```

  Store resulting `backups/postgres/*.dump` files outside the repo, preferably in encrypted object
  storage. Render-managed Postgres backups should remain enabled as the primary restore path.
- Configure production `CORS_ORIGINS`.
- Add uptime/error monitoring and a basic source-health check.
- Keep SMTP disabled until provider credentials are ready. Unsubscribe links and per-run rate limits
  are implemented; bounce handling is still provider/manual-ops work.

## Reference Links

- [Render Blueprint YAML reference](https://render.com/docs/blueprint-spec)
- [Render persistent disks](https://render.com/docs/disks/)
- [Render Postgres extensions](https://render.com/docs/postgresql-extensions)
- [Cloudflare Access application paths](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/app-paths/)
