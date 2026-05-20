# Phased Implementation Checklist

Last updated: 2026-05-20

## Phase 0 - Research and Data Feasibility

Goal: prove Huntsville is a viable pilot and document the source/legal/geometry constraints before building production workflows.

- [x] Confirm Huntsville pilot boundary.
- [x] Review Huntsville GIS/Data Depot usage terms.
- [x] Test ArcGIS REST queries for New Subdivisions.
- [x] Test ArcGIS REST queries for Building Permits.
- [x] Download or query a small sample from each source.
- [x] Verify source SRID and geometry transformation.
- [x] Inspect Planning Commission agenda PDFs from at least 6 months.
- [x] Identify whether agenda items can be matched to subdivision polygons.
- [x] Inventory local environmental/context layers from Huntsville GIS.
- [x] Decide which local layers can be stored versus linked live.
- [x] Document data gaps and uncertainty.

Acceptance criteria:

- [x] `docs/data-sources/huntsville-al.md` includes confirmed source URLs, access method, useful fields, and caveats.
- [x] At least one sample New Subdivisions query works.
- [x] At least one sample Building Permits query works.
- [x] At least one agenda PDF has been inspected for parseability.
- [x] The team has a written position on Huntsville data caching/redistribution risk.

## Phase 1 - Web MVP With Seed/Demo Data

Goal: build the basic application shell using representative seed data before relying on live ingestion.

- [x] Scaffold monorepo.
- [x] Add FastAPI app.
- [x] Add React/Vite frontend.
- [x] Add Docker Compose with Postgres/PostGIS.
- [x] Add SQLAlchemy/GeoAlchemy2 models and Alembic migrations.
- [x] Add seed data for development records.
- [x] Add seed environmental overlays or simplified fixtures.
- [x] Build MapLibre map.
- [x] Add layer toggles and filters.
- [x] Add development popup and detail page.
- [x] Add source attribution and confidence badges.
- [x] Add basic reviewer queue using seed staged records.
- [x] Add unit, integration, frontend, and E2E test scaffolding.
- [x] Add developer setup docs.

Acceptance criteria:

- [x] `docker compose up` starts API, web, Postgres, and Redis if used.
- [x] Web map renders seed records.
- [x] Record detail pages show source URL, agency, dates, confidence, geometry source, and review status.
- [x] Basic reviewer flow can approve a staged seed record.
- [x] Tests run with documented commands.

## Phase 2 - Real Huntsville Ingestion

Goal: ingest at least one real Huntsville future-development source and one issued-development context source.

- [x] Implement generic ArcGIS REST connector.
- [x] Implement Huntsville New Subdivisions connector config.
- [x] Implement Huntsville Building Permits connector config.
- [x] Store raw source payloads.
- [x] Normalize records into staging.
- [x] Validate geometry and source fields.
- [x] Dedupe staged records.
- [x] Publish reviewed New Subdivisions records.
- [x] Publish Building Permits as point context with low/medium geometry confidence.
- [x] Compute proximity flags for polygon subdivision records.
- [x] Import or link selected environmental layers.
- [x] Add source health monitoring.

Acceptance criteria:

- [x] A reproducible ingestion command fetches Huntsville New Subdivisions.
- [x] Published subdivision polygons render on the map.
- [x] Published records link back to source service or source page.
- [x] At least one environmental proximity flag is computed with a testable method.
- [x] Ingestion errors are logged and visible to maintainers.

## Phase 3 - PDFs, Public Submissions, Alerts, and Reviewer Tooling

Goal: make the app useful for ongoing public monitoring.

- [x] Implement Planning Commission agenda archive fetcher.
- [x] Store agenda PDFs and extracted text.
- [x] Parse candidate agenda items into staged records.
- [x] Require reviewer approval for PDF-derived records.
- [x] Add public submission form.
- [x] Add reviewer moderation for submissions.
- [x] Add watch areas.
- [x] Add email alerts for new or changed records.
- [x] Add record version history and public change log.
- [x] Improve duplicate detection across ArcGIS and PDF sources.

Acceptance criteria:

- [x] A user can draw or define a watch area.
- [x] A user can receive an alert for a new reviewed record intersecting or near the watch area.
- [x] A user can submit a public source link.
- [x] A reviewer can approve, reject, or request more information.
- [x] PDF-derived records clearly show source document, parse confidence, and review status.

## Phase 4 - Expansion Hardening

Goal: prepare for additional cities/counties without turning the codebase into source-specific spaghetti.

- [x] Generalize source connector configs.
- [x] Add source onboarding documentation.
- [x] Add jurisdiction configuration.
- [x] Add connector health dashboard.
- [x] Add privacy and safety review checklist.
- [x] Add import/export for reviewer decisions.
- [x] Add performance tests for larger source volumes.

Acceptance criteria:

- [x] A second pilot source can be added mostly through config plus a small parser.
- [x] Source health is visible for all active connectors.
- [x] The docs explain how maintainers add a local source.
