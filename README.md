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

## Planning Documents

- [v0.1-alpha Release Note](docs/releases/v0.1-alpha.md)
- [Architecture](docs/architecture.md)
- [Next Steps](docs/next-steps.md)
- [Huntsville Data Sources](docs/data-sources/huntsville-al.md)
- [Implementation Checklist](docs/implementation-checklist.md)
- [Follow-Up Codex Prompts](docs/follow-up-prompts.md)
- [Developer Setup](docs/developer-setup.md)
- [Deployment Plan](docs/deployment.md)
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

The API will serve processed ingestion artifacts from `data/processed/` when they exist, and otherwise falls back to seed/demo data.

## Important Caveat

This project should not make legal, permitting, ecological, engineering, flood insurance, or environmental-impact determinations. It should present public records and screening-level context with clear source attribution and uncertainty.
