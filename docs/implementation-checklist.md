# Phased Implementation Checklist

Last updated: 2026-05-20

## Phase 0 - Research and Data Feasibility

Goal: prove Huntsville is a viable pilot and document the source/legal/geometry constraints before building production workflows.

- [ ] Confirm Huntsville pilot boundary.
- [ ] Review Huntsville GIS/Data Depot usage terms.
- [ ] Test ArcGIS REST queries for New Subdivisions.
- [ ] Test ArcGIS REST queries for Building Permits.
- [ ] Download or query a small sample from each source.
- [ ] Verify source SRID and geometry transformation.
- [ ] Inspect Planning Commission agenda PDFs from at least 6 months.
- [ ] Identify whether agenda items can be matched to subdivision polygons.
- [ ] Inventory local environmental/context layers from Huntsville GIS.
- [ ] Decide which local layers can be stored versus linked live.
- [ ] Document data gaps and uncertainty.

Acceptance criteria:

- [ ] `docs/data-sources/huntsville-al.md` includes confirmed source URLs, access method, useful fields, and caveats.
- [ ] At least one sample New Subdivisions query works.
- [ ] At least one sample Building Permits query works.
- [ ] At least one agenda PDF has been inspected for parseability.
- [ ] The team has a written position on Huntsville data caching/redistribution risk.

## Phase 1 - Web MVP With Seed/Demo Data

Goal: build the basic application shell using representative seed data before relying on live ingestion.

- [ ] Scaffold monorepo.
- [ ] Add FastAPI app.
- [ ] Add React/Vite frontend.
- [ ] Add Docker Compose with Postgres/PostGIS.
- [ ] Add SQLAlchemy/GeoAlchemy2 models and Alembic migrations.
- [ ] Add seed data for development records.
- [ ] Add seed environmental overlays or simplified fixtures.
- [ ] Build MapLibre map.
- [ ] Add layer toggles and filters.
- [ ] Add development popup and detail page.
- [ ] Add source attribution and confidence badges.
- [ ] Add basic reviewer queue using seed staged records.
- [ ] Add unit, integration, frontend, and E2E test scaffolding.
- [ ] Add developer setup docs.

Acceptance criteria:

- [ ] `docker compose up` starts API, web, Postgres, and Redis if used.
- [ ] Web map renders seed records.
- [ ] Record detail pages show source URL, agency, dates, confidence, geometry source, and review status.
- [ ] Basic reviewer flow can approve a staged seed record.
- [ ] Tests run with documented commands.

## Phase 2 - Real Huntsville Ingestion

Goal: ingest at least one real Huntsville future-development source and one issued-development context source.

- [ ] Implement generic ArcGIS REST connector.
- [ ] Implement Huntsville New Subdivisions connector config.
- [ ] Implement Huntsville Building Permits connector config.
- [ ] Store raw source payloads.
- [ ] Normalize records into staging.
- [ ] Validate geometry and source fields.
- [ ] Dedupe staged records.
- [ ] Publish reviewed New Subdivisions records.
- [ ] Publish Building Permits as point context with low/medium geometry confidence.
- [ ] Compute proximity flags for polygon subdivision records.
- [ ] Import or link selected environmental layers.
- [ ] Add source health monitoring.

Acceptance criteria:

- [ ] A reproducible ingestion command fetches Huntsville New Subdivisions.
- [ ] Published subdivision polygons render on the map.
- [ ] Published records link back to source service or source page.
- [ ] At least one environmental proximity flag is computed with a testable method.
- [ ] Ingestion errors are logged and visible to maintainers.

## Phase 3 - PDFs, Public Submissions, Alerts, and Reviewer Tooling

Goal: make the app useful for ongoing public monitoring.

- [ ] Implement Planning Commission agenda archive fetcher.
- [ ] Store agenda PDFs and extracted text.
- [ ] Parse candidate agenda items into staged records.
- [ ] Require reviewer approval for PDF-derived records.
- [ ] Add public submission form.
- [ ] Add reviewer moderation for submissions.
- [ ] Add watch areas.
- [ ] Add email alerts for new or changed records.
- [ ] Add record version history and public change log.
- [ ] Improve duplicate detection across ArcGIS and PDF sources.

Acceptance criteria:

- [ ] A user can draw or define a watch area.
- [ ] A user can receive an alert for a new reviewed record intersecting or near the watch area.
- [ ] A user can submit a public source link.
- [ ] A reviewer can approve, reject, or request more information.
- [ ] PDF-derived records clearly show source document, parse confidence, and review status.

## Phase 4 - Expansion Hardening

Goal: prepare for additional cities/counties without turning the codebase into source-specific spaghetti.

- [ ] Generalize source connector configs.
- [ ] Add source onboarding documentation.
- [ ] Add jurisdiction configuration.
- [ ] Add connector health dashboard.
- [ ] Add privacy and safety review checklist.
- [ ] Add import/export for reviewer decisions.
- [ ] Add performance tests for larger source volumes.

Acceptance criteria:

- [ ] A second pilot source can be added mostly through config plus a small parser.
- [ ] Source health is visible for all active connectors.
- [ ] The docs explain how maintainers add a local source.

