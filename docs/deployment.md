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
- Email delivery: keep queued alerts internal until a provider-backed mail worker is added.

This keeps infrastructure small while avoiding a user-auth buildout.

## Render Setup Notes

API service:

- Dockerfile path: `apps/api/Dockerfile`.
- Docker context: `apps/api`.
- Start command: use the Dockerfile default. It runs migrations and starts Uvicorn on
  `${PORT:-8000}`.
- Required environment variables:
  - `DATABASE_URL`: Render Postgres internal connection URL, using the SQLAlchemy driver prefix if
    needed.
  - `INGESTION_DATA_DIR`: `/app/data`.
  - `CORS_ORIGINS`: production web origin.
  - `REVIEWER_API_TOKEN`: generated secret shared only with reviewers.

Web static site:

- Build command from the repo root: `npm install && npm --workspace apps/web run build`.
- Publish directory: `apps/web/dist`.
- Required environment variable:
  - `VITE_API_BASE_URL`: deployed API origin, or an empty same-origin path if a reverse proxy maps
    `/api` to the API service.

Data persistence:

- The current API can read processed ingestion artifacts from `INGESTION_DATA_DIR`.
- Render service filesystems are ephemeral unless a persistent disk is attached.
- A disk can be attached to the API service at `/app/data`, but it cannot be shared with a Render
  cron job. The durable next step is moving ingestion outputs into Postgres or object storage before
  automated hosted ingestion is considered complete.

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

- Set `REVIEWER_API_TOKEN` and verify private reviewer API routes return `401` without it.
- Put `/review` and `/api/reviewer/*` behind an edge access policy.
- Decide whether the first public alpha uses seed/demo data, a manually uploaded artifact snapshot,
  or a short database-persistence pass for ingestion output.
- Configure database backups and PostGIS.
- Configure production `CORS_ORIGINS`.
- Add uptime/error monitoring and a basic source-health check.
- Keep SMTP disabled until unsubscribe, bounce handling, and provider credentials are ready.

## Reference Links

- [Render Blueprint YAML reference](https://render.com/docs/blueprint-spec)
- [Render persistent disks](https://render.com/docs/disks/)
- [Render Postgres extensions](https://render.com/docs/postgresql-extensions)
- [Cloudflare Access application paths](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/app-paths/)
