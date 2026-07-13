# Urbanization Tracker

Urbanization Tracker is an open-source public-good application for helping people understand current development, proposed or approved future development, and environmental context around that development.

The first pilot geography is **Huntsville, Alabama**.

This repository is now through Phase 4: a Huntsville alpha with live ArcGIS ingestion, Planning Commission agenda PDF ingestion, reviewer-gated public submissions, watch areas, queued alerts, source-aware map/reviewer UI, and expansion hardening for additional jurisdictions.

## Goals

- Show development activity on an interactive web map.
- Connect development records to source agencies, source URLs, documents, dates, confidence levels, and review status.
- Add conservative environmental context such as nearby wetlands, waterways, floodplains, protected lands, wildlife refuges, and impervious-surface change.
- Treat future-development data as fragmented, local, inconsistent, and often reviewer-gated.
- Prioritize transparency, maintainability, accessibility, low operating cost, provenance, and public trust over visual flash.

## Current Direction

- Pilot: City of Huntsville, AL.
- Backend: FastAPI, SQLAlchemy, Alembic, PostgreSQL/PostGIS.
- Frontend: React, TypeScript, Vite, MapLibre GL JS.
- Ingestion: Python ETL connectors for ArcGIS REST services, static geospatial downloads, public APIs, webpages, PDFs/agendas, and manual submissions.
- Reviewer workflow: custom lightweight admin/reviewer UI rather than Django Admin.

## Project Status

Last verified: **2026-07-12**.

The application is a code-complete Phase 4 alpha with production deployment scaffolding. It is not
yet a verified public production service. The repository includes Postgres-backed operational and
processed stores, Render cron definitions, deployment preflight checks, source-freshness
monitoring, reviewer operations, and a live Madison County subdivision connector in addition to
the Huntsville pilot sources.

Current verification passes API and web lint/typechecking, 60 API tests, 4 web unit tests, the web
production build, and 2 Chromium end-to-end smoke tests. The latest local ingestion snapshot was
captured on 2026-06-19; it is useful as a development artifact but should not be treated as current
public data.

The remaining launch work is environment-specific: provision the hosted services, set production
secrets and HTTPS origins, migrate existing collections into Postgres, verify PostGIS and backups,
protect reviewer routes at the edge, configure artifact storage and monitoring, and decide when to
enable scheduled ingestion and outbound email.

## Planning Documents

- [v0.1-alpha Release Note](docs/releases/v0.1-alpha.md)
- [Architecture](docs/architecture.md)
- [Next Steps](docs/next-steps.md)
- [Huntsville Data Sources](docs/data-sources/huntsville-al.md)
- [Implementation Checklist](docs/implementation-checklist.md)
- [Follow-Up Codex Prompts](docs/follow-up-prompts.md)
- [Developer Setup](docs/developer-setup.md)
- [Deployment Plan](docs/deployment.md)
- [Operations Monitoring](docs/operations-monitoring.md)
- [Phase 2 Ingestion](docs/phase-2-ingestion.md)
- [Phase 3 Monitoring](docs/phase-3-monitoring.md)
- [Phase 4 Expansion Hardening](docs/phase-4-expansion-hardening.md)
- [Source Onboarding](docs/source-onboarding.md)
- [Privacy And Safety Checklist](docs/privacy-safety-checklist.md)

## Local Quick Start

```bash
docker compose up --build
```

Then open:

- Web app: http://localhost:5173
- API health: http://localhost:8000/health

For local non-Docker development, see [Developer Setup](docs/developer-setup.md).

## Huntsville Ingestion

```bash
make ingest-huntsville
make ingest-huntsville-agendas
```

The API will serve processed ingestion output when it exists, and otherwise falls back to seed/demo
data. Local development uses `data/processed/`; hosted environments can use
`PROCESSED_STORE_BACKEND=postgres` for canonical processed collections while raw payloads remain
artifacts.

## Important Caveat

This project should not make legal, permitting, ecological, engineering, flood insurance, or environmental-impact determinations. It should present public records and screening-level context with clear source attribution and uncertainty.
