# Next Steps

Last updated: 2026-07-09

The codebase is through Phase 4 and has the application and deployment plumbing needed for a
private alpha. The critical path is now production configuration and operational verification, not
another broad feature phase.

## Completed Hardening

- [x] Add Postgres-backed Phase 3 operational collections, migration tooling, and status APIs.
- [x] Add Postgres-backed canonical processed collections and migration tooling.
- [x] Configure hosted API and cron definitions to use Postgres stores.
- [x] Add scheduled Huntsville ArcGIS, Huntsville agenda, Madison County, and alert-delivery jobs to
  the Render Blueprint.
- [x] Add deployment preflight checks for reviewer protection, HTTPS origins, persistence, alert
  configuration, database connectivity, and PostGIS.
- [x] Add source-freshness monitoring suitable for an external uptime check.
- [x] Replace bounding-box-only proximity decisions with geometry intersection and distance checks,
  backed by floodplain and wetland regression fixtures.
- [x] Add reviewer decision import/export and bounded alert-delivery controls.
- [x] Track raw artifact hashes, sizes, source keys, and intended storage URIs in an artifact
  manifest.
- [x] Add a live Madison County subdivision connector while retaining the inactive demo fixture for
  onboarding examples.

## Private Alpha Deployment

- [ ] Provision the Render Blueprint or an equivalent API, static web app, Postgres/PostGIS database,
  and scheduled-job environment.
- [ ] Set `REVIEWER_API_TOKEN`, production `CORS_ORIGINS`, `PUBLIC_BASE_URL`, and
  `VITE_API_BASE_URL`.
- [ ] Protect `/review` and `/api/reviewer/*` with an edge access policy in addition to the API token.
- [ ] Run Alembic migrations and migrate any existing processed and Phase 3 artifact collections
  into the hosted database.
- [ ] Run `make deployment-preflight` against the deployed database and resolve every failed check.
- [ ] Confirm PostGIS, managed backups, restore ownership, and an external uptime/error monitor for
  both `/health` and `/health/source-health`.
- [ ] Choose whether the first alpha starts from a manually reviewed snapshot or immediately enables
  the scheduled ingestion jobs.
- [ ] Choose and configure durable object storage for raw ArcGIS payloads, agenda PDFs, extracted
  text, and generated artifacts.

## Operational Follow-Up

- [ ] Display processed-store and Phase 3 store status in the reviewer UI; the API and CLI status
  surfaces already exist.
- [ ] Keep outbound alerts disabled until SMTP credentials, unsubscribe behavior, rate limiting, and
  production delivery have been verified end to end.
- [ ] Add a bounce/complaint handling runbook once an email provider is selected.
- [ ] Replace local geometry calculations with normalized PostGIS predicates and distances for the
  durable spatial model.
- [ ] Continue improving public-submission moderation and duplicate-resolution affordances based on
  reviewer feedback.

## Engineering Cleanup

- [ ] Split the web bundle; the current production JavaScript chunk is roughly 1 MB minified.
- [ ] Expand browser coverage beyond the two Chromium smoke tests as reviewer workflows stabilize.
- [ ] Keep this file and the release note synchronized with deployment changes.
