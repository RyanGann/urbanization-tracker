# E03 — Build versioned pilot raster tiles and comparison summaries

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Environmental expansion / G4 |
| Depends on | [E02](E02-land-cover-source-spike.md), [O01](O01-durable-artifact-uploads.md), [P05](P05-versioned-vector-tile-api.md) |
| Review | Lead review |
| PR boundary | One offline raster build/serve PR for the two selected years only. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

The selected land-cover products need a reproducible, bounded delivery format before a comparison UI can be truthful or performant.

## Code to inspect

- [apps/api/app/ingestion/artifacts.py](../../../apps/api/app/ingestion/artifacts.py)
- [apps/api/app/ingestion/cli.py](../../../apps/api/app/ingestion/cli.py)
- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)
- [apps/api/app/config.py](../../../apps/api/app/config.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Implement one offline build command for E02's fixed product/years/pilot extent, using a pinned GDAL/rasterio toolchain in a reproducible worker image. Preserve original raster artifacts and manifests in O01 storage.

2. Align/mask the two inputs per E02, then generate immutable pre-rendered XYZ raster tiles at a documented limited zoom range and a small pilot summary artifact. This PR does not build an on-demand arbitrary raster calculation service.

3. Version outputs by source checksums, grid/mask, comparison/rule and rendering palette. Retain data-year versus processed-at separately. Verify nodata does not become zero imperviousness or a land-cover class.

4. Extend the catalog with an explicit raster layer kind, legend/classes, tile template, pixel resolution, data years and limitations. Add a bounded versioned raster-tile reader using the established cache/error principles; share helpers without changing MVT source-layer semantics.

5. Report valid-data area, class/transition areas and impervious change with documented units and uncertainty. Use an equal-area calculation appropriate to the product, not Web Mercator pixel area.

6. Validate complete artifacts before atomically exposing a raster version. Enforce storage/zoom/build-time caps for the pilot and retain a prior working version on failure.

## Acceptance and verification

- [ ] Tiny known rasters match expected class transitions, percentage-point changes, nodata and area totals.
- [ ] Generated tile edges/palettes align across years; source coordinates and known landmarks are visually checked.
- [ ] Interrupted build cannot publish partial years; cache URLs change when source/rule/palette changes.
- [ ] Delivery stays within application transfer budgets; no full raster download reaches the browser.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Shadow-build two selected years, inspect fixed samples and summary arithmetic, then enable the catalog entries in a restricted environment.

## Outside this PR

No live arbitrary-area raster analytics, national tile pyramid, satellite acquisition service or machine-learning attribution.

## Agent handoff

> Implement E03 only, after its dependencies are merged. Implement a bounded offline two-year raster build and versioned delivery with tested nodata/alignment/area semantics. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
