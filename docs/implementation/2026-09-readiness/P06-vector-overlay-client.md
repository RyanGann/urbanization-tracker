# P06 — Render catalog-driven vector overlays without bulk GeoJSON

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Performance / G2 |
| Depends on | [P02](P02-layer-catalog-startup-relief.md), [P05](P05-versioned-vector-tile-api.md), [S01](S01-frontend-dependency-update.md) |
| Review | Routine coding agent |
| PR boundary | One environmental map-client PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The [performance plan](PERFORMANCE.md) fixes the architecture, budgets and measurement protocol for this PR. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

The current component upserts every full GeoJSON source whenever overlay visibility or records change. Actual source IDs also differ from seeded defaults.

## Code to inspect

- [apps/web/src/api.ts](../../../apps/web/src/api.ts)
- [apps/web/src/types.ts](../../../apps/web/src/types.ts)
- [apps/web/src/pages/MapPage.tsx](../../../apps/web/src/pages/MapPage.tsx)
- [apps/web/src/components/DevelopmentMap.tsx](../../../apps/web/src/components/DevelopmentMap.tsx)
- [apps/web/src/styles.css](../../../apps/web/src/styles.css)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Use the layer catalog as the only definition of available IDs, labels, coverage, attribution and tile templates. Resolve relative tile paths against the configured API origin, preserving literal {z}/{x}/{y} tokens; the website and API may use different hosts. Add MapLibre vector sources with source-layer 'environment', versioned tile URLs, bounds and min/max zoom.

2. Request/render only enabled layers; use layout visibility changes for toggles and do not call GeoJSON setData. If hidden source requests continue with the installed MapLibre version, remove/re-add the hidden vector source/layers while preserving control state.

3. Separate map initialization, record-source updates, overlay-source version changes, visibility updates and selection effects. Manage source/layer order deterministically and detach handlers on unmount.

4. On a catalog version change, install the new version and switch when ready; retain the previous visible version while a replacement loads or fails, explicitly marked stale. Do not erase overlays merely because catalog revalidation is pending.

5. Show preparation, zoom restriction, partial/stale coverage, tile error and unavailable states near the legend. A failed tile must not look like proof that an area has no wetlands/floodplain.

6. For the final pilot default, enable ready floodplain/wetland layers by their actual catalog IDs unless a URL/user choice says otherwise. Use a readable fill-opacity hierarchy and accessible non-color labels.

## Acceptance and verification

- [ ] Live browser network trace shows catalog + visible tiles and zero legacy overlay requests on load/toggle/pan.
- [ ] Toggle one layer ten times: unrelated sources are not rebuilt, map selection stays stable, and hidden layers make no new geometry requests.
- [ ] Catalog version activation/rollback, failed tile, zoom boundary and stale source states render correctly.
- [ ] Inspect dense geometry, holes, attribution, mobile controls and keyboard focus against the real API. The live test uses distinct web/API origins and confirms tile requests reach the API with valid CORS behavior.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Merge only after P05 tile correctness and S01 dependency compatibility pass. Remove unused bulk-overlay imports/types from the public route; keep any offline legacy export separate.

## Outside this PR

No basemap switch, development query redesign, 3D map, or automatic fallback to the full JSON payload.

## Agent handoff

> Implement P06 only, after its dependencies are merged. Switch environmental rendering to versioned catalog-driven tiles and isolate map effects so visibility changes do not reparse data. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
