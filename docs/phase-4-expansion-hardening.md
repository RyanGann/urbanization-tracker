# Phase 4 Expansion Hardening

Phase 4 prepares the project for a second source or jurisdiction without scattering source-specific
logic through the app.

## What Changed

- Jurisdiction/source config files live in `apps/api/app/jurisdictions/`.
- `GET /api/jurisdictions` lists configured jurisdictions and sources.
- `GET /api/connector-health` shows health for every active configured connector, including sources
  that have not run yet.
- Madison County now has a live ArcGIS subdivision source:
  `madison_county_subdivisions`.
- Reviewer decisions can be exported and imported:
  - `GET /api/reviewer/decisions/export`
  - `POST /api/reviewer/decisions/import`
- Larger-volume performance smoke tests cover GeoJSON serialization and duplicate candidate
  generation.
- Source onboarding and privacy/safety docs are now explicit:
  - [Source Onboarding](source-onboarding.md)
  - [Privacy And Safety Checklist](privacy-safety-checklist.md)

## Second Pilot Shape

`apps/api/app/jurisdictions/madison-county-al.json` introduces a real second jurisdiction through
the Huntsville-hosted Madison County subdivisions ArcGIS layer. Its parser publishes recorded
subdivision polygons as `completed` subdivision context with explicit legal/status caveats.

`apps/api/app/jurisdictions/madison-county-al-demo.json` is now inactive and retained only as the
smallest static-fixture onboarding example.

## Connector Health

The connector health dashboard combines:

- active source configs
- latest ingestion source health
- privacy review notes
- safety review notes
- records seen/created
- error counts

This makes missing runs visible as `not_run` instead of silently disappearing from operations views.

## Reviewer Decision Handoff

Decision export/import is meant for reviewer backups, audits, and small operational handoffs. It is
not a replacement for database-backed review events, but it gives maintainers a practical local MVP
workflow until Phase 4+ database persistence is wired fully.
