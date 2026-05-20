# Urbanization Tracker

Urbanization Tracker is an open-source public-good application for helping people understand current development, proposed or approved future development, and environmental context around that development.

The first pilot geography is **Huntsville, Alabama**.

This repository is currently in the planning and architecture phase. No production application code has been added yet.

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

- [Architecture](docs/architecture.md)
- [Huntsville Data Sources](docs/data-sources/huntsville-al.md)
- [Implementation Checklist](docs/implementation-checklist.md)
- [Follow-Up Codex Prompts](docs/follow-up-prompts.md)

## Important Caveat

This project should not make legal, permitting, ecological, engineering, flood insurance, or environmental-impact determinations. It should present public records and screening-level context with clear source attribution and uncertainty.

