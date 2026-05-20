# Follow-Up Codex Prompts

Use these prompts to implement the app in manageable chunks. Each prompt assumes the previous planning docs exist in the repo.

## 1. Scaffold the Monorepo

```text
Scaffold the Urbanization Tracker monorepo according to docs/architecture.md. Create a FastAPI backend, React/Vite frontend, Docker Compose with PostgreSQL/PostGIS and Redis, Makefile commands, and minimal health checks. Do not implement ingestion yet.
```

## 2. Add the Database Model

```text
Implement the initial SQLAlchemy/GeoAlchemy2 models and Alembic migrations for the core entities in docs/architecture.md: agencies, data_sources, ingestion_runs, source_documents, raw_records, staged_development_records, development_records, record_geometries, environmental_layers, environmental_features, proximity_flags, review_events, record_versions, user_submissions, watch_areas, and alerts. Add focused tests for migrations and model constraints.
```

## 3. Build the Seed Web Map

```text
Build the first public web map using MapLibre GL JS and seed data. Include layer toggles, development status filters, confidence badges, popups, and development detail pages. Use only seed/demo records for now.
```

## 4. Add Reviewer Queue MVP

```text
Create a small internal reviewer workflow for staged development records. Reviewers should be able to inspect source fields, preview geometry, approve, reject, mark needs-info, and publish to canonical development_records. Keep the UI narrow and practical.
```

## 5. Implement Generic ArcGIS REST Ingestion

```text
Implement the generic ArcGIS REST connector described in docs/architecture.md. It should read layer metadata, paginate query results, request GeoJSON where possible, store raw payloads, normalize records into staging, and log ingestion health. Add frozen HTTP fixture tests.
```

## 6. Add Huntsville New Subdivisions Connector

```text
Using docs/data-sources/huntsville-al.md, add a connector configuration and normalization mapping for the Huntsville New Subdivisions ArcGIS layer. Ingest polygon records into staging, map Layout/Preliminary/Final source statuses to public statuses, and add tests using frozen fixtures.
```

## 7. Add Huntsville Building Permits Connector

```text
Using docs/data-sources/huntsville-al.md, add a connector configuration and normalization mapping for the Huntsville Building Permits ArcGIS layer. Treat permit geometries as point context with explicit geometry confidence. Add tests using frozen fixtures.
```

## 8. Add Environmental Proximity Flags

```text
Implement environmental proximity flag computation in PostGIS for wetlands, waterways, floodplains, protected lands, refuges, critical habitat, and impervious-growth context. Use conservative labels and add geospatial fixture tests with known expected distances/intersections.
```

## 9. Add Planning Commission PDF Ingestion

```text
Implement a reviewer-gated Planning Commission agenda ingestion flow. Fetch the Huntsville agenda archive, store PDFs, extract text, parse candidate agenda items into staged records, and require reviewer approval before publishing. Add PDF fixture tests and clear confidence labels.
```

## 10. Add Watch Areas and Alerts

```text
Add public watch areas and email alerts. Users should be able to define a watch area, choose filters, and receive notifications when new or changed reviewed records match. Include unsubscribe and privacy-safe storage.
```

## 11. Harden Testing and CI

```text
Add comprehensive lint, typecheck, unit, integration, geospatial, frontend, and Playwright E2E tests. Add CI configuration and document all commands in the README.
```

## 12. Prepare Source Onboarding Docs

```text
Write documentation for adding a new city or county data source. Include ArcGIS REST, open-data APIs, static downloads, webpages, PDFs, manual submissions, licensing review, geometry confidence, and reviewer workflow expectations.
```

