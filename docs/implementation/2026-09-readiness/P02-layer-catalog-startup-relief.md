# P02 — Serve a small layer catalog and stop eager bulk overlay downloads

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Performance / G1 |
| Depends on | [P01](P01-performance-baseline.md), [C01](C01-explicit-data-modes.md) |
| Review | Routine coding agent |
| PR boundary | One immediate startup-relief PR; tiles remain a later step. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The [performance plan](PERFORMANCE.md) fixes the architecture, budgets and measurement protocol for this PR. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

Map startup currently fetches every environmental geometry even when overlays are hidden. Layer discovery needs names, coverage and delivery state, not 129 MB of polygons.

## Code to inspect

- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)
- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [apps/api/app/ingestion/pipeline.py](../../../apps/api/app/ingestion/pipeline.py)
- [apps/api/app/processed_store.py](../../../apps/api/app/processed_store.py)
- [apps/web/src/api.ts](../../../apps/web/src/api.ts)
- [apps/web/src/types.ts](../../../apps/web/src/types.ts)
- [apps/web/src/pages/MapPage.tsx](../../../apps/web/src/pages/MapPage.tsx)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Add GET /api/map/layers using CONTRACTS.md. Persist a small catalog during ingestion or an explicit offline backfill command. Never derive the catalog by loading the 365 MB artifact inside the request handler.

2. Include stable real IDs, title/category, source attribution, extent, coverage state/counts, data/fetch times, current version, min/max zoom, delivery_status and optional tile template. Distinguish absent data from a supported but not yet tile-ready layer.

3. Change map startup to request only the catalog. Remove eager useQuery/getEnvironmentalOverlays from the public map. Until P06 is merged, show known environmental layers as temporarily unavailable with a clear preparation reason; do not silently claim the feature is ready.

4. Keep the legacy bulk endpoint only for explicit offline/debug compatibility, not as an automatic browser fallback. No page-load or layer-toggle path may initiate that full download.

5. Initialize control IDs from catalog entries, preserving explicit user choices. Add accessible catalog loading/error/empty states and attribution text; no hard-coded seed overlay IDs.

6. Add cache revalidation for the small catalog and invalidate its generation when metadata changes. P03/P04 will supply immutable tile versions; do not invent tile URLs before those endpoints exist.

## Acceptance and verification

- [ ] Real browser cold load and all control toggles issue zero requests to /api/environmental-overlays.
- [ ] Catalog response has no feature arrays/coordinates and is <=50 KiB decoded on the representative fixture.
- [ ] Monkeypatch or spy on the legacy bulk reader in an API test: catalog requests must not call it.
- [ ] Catalog missing/failed/demo states remain distinct; the two real Huntsville layer IDs appear correctly.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

This is a temporary internal-preview improvement, not completion of environmental display. Explain the unavailable controls in release notes and require P06 before the map usability gate.

## Outside this PR

No per-layer download of the same huge JSON, in-request simplification, Redis cache, or pretending unavailable overlays are switched on.

## Agent handoff

> Implement P02 only, after its dependencies are merged. Remove the startup bulk download, add persisted metadata discovery, and show honest tile-preparation states. Do not implement vector delivery yet. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
