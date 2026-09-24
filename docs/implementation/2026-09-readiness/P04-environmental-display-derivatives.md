# P04 — Prepare display geometry and activate complete layer versions atomically

Execution status: [plan.json](plan.json), entry `P04`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Performance / G1 |
| Depends on | [P03](P03-canonical-environmental-storage.md), [D01](D01-source-scope-pagination-canaries.md), [O01](O01-durable-artifact-uploads.md) |
| Review | Lead review |
| PR boundary | One spatial display-preprocessing/activation PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The [performance plan](PERFORMANCE.md) fixes the architecture, budgets and measurement protocol for this PR. The steps below define this guide's scope; use its manifest entry and evidence to determine current capability.

## Problem and intended result

Full-resolution geometry cannot be clipped and serialized repeatedly on every map request. Display optimization must not alter scientific screening geometry.

## Code to inspect

- [apps/api/app/models.py](../../../apps/api/app/models.py)
- [apps/api/app/ingestion/pipeline.py](../../../apps/api/app/ingestion/pipeline.py)
- [apps/api/app/ingestion/cli.py](../../../apps/api/app/ingestion/cli.py)
- [apps/api/app/ingestion/geometry.py](../../../apps/api/app/ingestion/geometry.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Create a derived display-parts table keyed by layer version, feature ID, zoom band and part number, with EPSG:3857 geometry and a GiST index. Canonical EPSG:4326 features remain the only source for environmental analysis.

2. Implement the initial zoom/tolerance table in PERFORMANCE.md. Transform once during preprocessing, simplify each original feature with ST_SimplifyPreserveTopology in projected units, then subdivide into bounded parts (initial max_vertices=256). Do not simplify independent clipped tiles or polygon parts, which can introduce inconsistent edges.

3. Preserve holes and multipolygons and retain source_feature_id on every part. Per-feature topology preservation does not guarantee shared boundaries between different features; include adjacent-polygon seam inspection. Initially render fill only, avoiding artificial subdivision outlines.

4. Validate counts, extents, maximum vertices, invalid/collapsed geometries and a set of dense sample tiles before marking a derivative version ready. Distinguish data_version from display_version; changing tolerances changes the latter.

5. Atomically switch a small active-layer pointer only after canonical data and required zoom bands are complete. The exact candidate must also have a P03 validated import with zero rejected features, D01 complete coverage for the same source scope/version/checksum, and O01-verified required raw artifacts. Unknown, partial or failed coverage stays a shadow attempt; never promote it by inferring completeness from accepted counts. Keep active and previous versions plus a minimum seven-day grace period for issued catalog URLs.

6. Add resumable build/cleanup commands; cleanup cannot remove active, retained or in-use versions. Failed/partial runs keep the previous layer and advertise attempted-refresh failure in metadata.

## Acceptance and verification

- [ ] Known small wetland, narrow channel, hole and multipolygon remain visually interpretable at the documented zoom; collapsed display geometry is counted and disclosed.
- [ ] Exact screening results against canonical geometry are identical before and after derivative generation.
- [ ] Kill preprocessing partway: no incomplete version appears; repeat build -> same version/checksum.
- [ ] A synthetic fully sourced candidate activates only when its import, scope coverage, derivative bands and raw artifacts all match the same data version. Mismatched or missing prerequisites leave the prior ready pointer intact and expose the attempted failure. The copied FEMA/wetlands snapshot is not a positive activation fixture because its import/coverage evidence is incomplete.
- [ ] Spatial query plans use the projected index at representative selective viewports; a rollback pointer restores the prior version.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Shadow-build and visually review sample tiles before activation. The tolerance table is an initial display budget, not a precision guarantee for property decisions.

## Outside this PR

No simplification of canonical geometry, inferred environmental absence at low zoom, or source-data changes.

## Agent handoff

> Implement P04 only, after its dependencies are merged. Build immutable zoom-specific display parts, with tests for holes/seams and atomic version activation. Keep all analysis on originals. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
