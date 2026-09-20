# E04 — Show a two-year land-cover and imperviousness comparison

Execution status: [plan.json](plan.json), entry `E04`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Environmental expansion / G4 |
| Depends on | [E03](E03-pilot-raster-artifacts.md), [U01](U01-filters-shareable-state-coverage.md) |
| Review | Routine with visual review |
| PR boundary | One comparison UI PR using the prepared raster products. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The steps below define this guide's scope; use its manifest entry and evidence to determine current capability.

## Problem and intended result

Users need a clear historical landscape comparison, with source dates and uncertainty, rather than an unlabeled heatmap implying development causation.

## Code to inspect

- [apps/web/src/pages/MapPage.tsx](../../../apps/web/src/pages/MapPage.tsx)
- [apps/web/src/components/DevelopmentMap.tsx](../../../apps/web/src/components/DevelopmentMap.tsx)
- [apps/web/src/types.ts](../../../apps/web/src/types.ts)
- [apps/web/src/api.ts](../../../apps/web/src/api.ts)
- [apps/web/src/styles.css](../../../apps/web/src/styles.css)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Add a two-year comparison control for E03's exact available years/products. Start with year toggling or opacity blending; avoid a complex synchronized dual-map implementation in the first PR.

2. Use the raster catalog kind/template and immutable versions; preserve existing development/environmental vector overlays and map URL state. Record selected product/year without leaking private watch state.

3. Provide separate legends and units for categorical land cover and impervious percentage/percentage-point change. Show pixel resolution, valid-data mask and source data years next to the comparison.

4. Display the precomputed pilot summary with its exact geographic scope and denominators. Do not present a pilot-wide number as the current viewport total.

5. Explain that observed change does not establish which permit/project caused it. Link authoritative source methods and preserve uncertainty and nodata visibility.

6. Keep keyboard controls, color-vision-friendly palettes, a textual summary and a usable mobile layout. Measure extra tile requests/memory and dispose unused raster sources.

## Acceptance and verification

- [ ] Select each year/product and reload a shared URL; labels, legend, tiles and summary remain consistent.
- [ ] Known fixture changes and nodata render correctly; impervious change uses percentage points, not misleading percent growth.
- [ ] Existing record selection and environmental toggles work during comparison and after returning to the normal map.
- [ ] Run live browser accessibility/performance checks and inspect representative raster boundaries.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Enable after E03 source/summary verification and show an explicit experimental comparison label until pilot review is complete.

## Outside this PR

No predicted development, causal attribution, generalized time-series dashboard or new upstream data sources.

## Agent handoff

> Implement E04 only, after its dependencies are merged. Build a simple, accessible two-year comparison using only the verified raster catalog and summaries. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
