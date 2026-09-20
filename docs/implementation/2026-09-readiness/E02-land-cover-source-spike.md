# E02 — Choose a comparable land-cover product and lock a small fixture

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Environmental expansion / G4 |
| Depends on | [O03](O03-restricted-alpha-rehearsal.md) |
| Review | Lead review |
| PR boundary | One bounded research/fixture PR, at most three working days. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

Impervious-surface and land-cover change are central original goals, but no production product/years/comparison method has been implemented.

## Code to inspect

- [docs/source-onboarding.md](../../source-onboarding.md)
- [docs/architecture.md](../../architecture.md)
- [docs/data-sources/huntsville-al.md](../../data-sources/huntsville-al.md)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Review current official USGS Annual NLCD access/product documentation and choose two available, comparable product years for the pilot. Record product release/version, class definitions, resolution, CRS, nodata, uncertainty and redistribution terms.

2. Define separate measures for land-cover class and fractional imperviousness. Do not equate a newly issued permit with observed land-cover change or subtract category codes as a numerical change measure.

3. Download or construct one small permitted fixture clipped to a documented pilot test area; record checksums and exact acquisition steps. If large source files are needed, store them as artifacts and commit only a small redistributable fixture/manifest.

4. Specify alignment/resampling: categorical nearest-neighbor, impervious product-specific handling, common pixel grid/extent/nodata mask. Define class transitions and area calculation units.

5. Produce an example two-year comparison with explicit data years and limitations, plus the fixed interfaces E03/E04 will implement. Record estimated storage/build cost for the pilot, not a nationwide service.

6. End with a proceed/revise decision based on source availability, comparability and licensing. If products cannot be compared honestly, document the alternative instead of inventing a trend.

## Acceptance and verification

- [ ] A reviewer can reproduce fixture acquisition and identify both source years/releases.
- [ ] Hand-computed tiny raster cases verify nodata exclusion, categorical transitions and impervious percentage-point change.
- [ ] Inspect alignment at boundaries and show how different releases/methodology could affect comparison.
- [ ] No production API/UI is changed by this spike.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Documentation, fixtures and a source decision only. E03 starts after the comparison contract is reviewed.

## Outside this PR

No generic raster platform, forecast model, full-country processing or promise that annual pixels establish project-level causation.

## Agent handoff

> Implement E02 only, after its dependencies are merged. Resolve product/year comparability and deliver a small reproducible land-cover fixture with an explicit comparison contract. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
