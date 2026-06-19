# Next Steps

Last updated: 2026-05-21

This is the working backlog for moving the alpha from local proof-of-concept workflows toward a
durable public deployment. Each item should be handled as a small reviewable slice, committed, and
opened as a GitHub pull request before moving to the next item.

## 1. Database-First Operational Persistence

Goal: keep generated raw files as audit artifacts, but move operational state into durable storage.

- [ ] Make Phase 3 operational collection status visible to reviewers and maintainers.
- [ ] Use `PHASE3_STORE_BACKEND=postgres` for hosted API, ingestion, alert, and reviewer workflows.
- [ ] Migrate existing `data/processed/phase3_*.json` collections with `make migrate-phase3-postgres`.
- [ ] Move canonical ingestion outputs away from `data/processed/development_records.json` and into
  Postgres-backed read/write paths.
- [ ] Keep bulky raw ArcGIS payloads, agenda PDFs, extracted text, and generated map artifacts as
  artifact/object-storage files referenced from database rows.

Decision needed later: choose the hosted artifact store before automating ingestion. Render disks
are acceptable for a narrow alpha, but S3-compatible storage such as R2/S3 is a better long-term
home for raw PDFs and raw GeoJSON payloads.

## 2. Hosted Ingestion Jobs

- [ ] Add scheduled Huntsville ArcGIS ingestion.
- [ ] Add scheduled Huntsville agenda ingestion.
- [ ] Add scheduled Madison County ingestion.
- [ ] Surface run failures through connector health and uptime/error monitoring.

## 3. Spatial Accuracy Hardening

- [ ] Replace bounding-box proximity calculations with PostGIS spatial predicates and distances.
- [ ] Add fixture tests for floodplain intersection and wetland distance thresholds.
- [ ] Keep public labels conservative and explicit about screening-level use.

## 4. Reviewer Operations

- [ ] Expose decision import/export in the reviewer UI.
- [ ] Expose Phase 3 store status in the reviewer UI.
- [ ] Add controls or documented runbooks for alert delivery batches.
- [ ] Improve public-submission moderation affordances.

## 5. Public Alpha Launch Readiness

- [ ] Set `REVIEWER_API_TOKEN`.
- [ ] Protect `/review` and `/api/reviewer/*` at the edge.
- [ ] Configure production `CORS_ORIGINS`.
- [ ] Confirm database backups and PostGIS extension.
- [ ] Decide whether initial public data comes from a manually reviewed snapshot or scheduled jobs.
- [ ] Configure SMTP only after unsubscribe and rate-limit behavior has been verified in production.
