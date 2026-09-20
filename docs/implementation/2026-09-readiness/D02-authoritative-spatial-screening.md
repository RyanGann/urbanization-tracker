# D02 — Calculate environmental screening from complete canonical geometry

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Data quality / G1 |
| Depends on | [D01](D01-source-scope-pagination-canaries.md), [P04](P04-environmental-display-derivatives.md), [C06](C06-publication-events-history.md) |
| Review | Lead review |
| PR boundary | One screening-engine replacement PR for existing wetlands/floodplain rules. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

Local geometry routines and partial overlays cannot establish reliable environmental relationships. Display simplification must never change published screening flags.

## Code to inspect

- [apps/api/app/ingestion/proximity.py](../../../apps/api/app/ingestion/proximity.py)
- [apps/api/app/ingestion/pipeline.py](../../../apps/api/app/ingestion/pipeline.py)
- [apps/api/app/models.py](../../../apps/api/app/models.py)
- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)
- [apps/api/tests/test_ingestion_proximity.py](../../../apps/api/tests/test_ingestion_proximity.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Move existing wetland/floodplain intersection and distance calculations into indexed PostGIS queries against canonical environmental versions. Use ST_Intersects for overlap and geography or an appropriate documented metric projection for distance; do not measure metres in EPSG:4326 degrees.

2. Store the development revision, environmental data version, rule version, threshold, result and computed_at for each evaluation. Bound candidate lookup spatially before exact predicates.

3. Use D01 coverage semantics: outside/incomplete/failed coverage produces unknown or partial screening, not a confident absence. Distinguish 'no mapped intersection in the stated dataset' from an ecological/legal conclusion.

4. Trigger bounded recomputation when development geometry, rule version or an active canonical layer changes. Write resulting public context through C06 as context_changed, notify_eligible=false by default; avoid alert storms from a routine environmental refresh.

5. Retain source attribution and caveats in public flags. Preserve earlier evaluation provenance so a reviewer can explain why a flag changed.

6. Compare the existing geometric fixtures with authoritative PostGIS results, documenting intentional differences around holes, boundaries and distances rather than preserving incorrect legacy output.

## Acceptance and verification

- [ ] Hole/bbox false positive, multipart geometry, touching boundary, within/exactly at/beyond threshold and coordinate-order cases run on real PostGIS.
- [ ] Partial/outside coverage cannot produce an unqualified negative; a failed layer refresh retains prior version and its age.
- [ ] Building new display derivatives or changing zoom leaves screening results unchanged.
- [ ] Rerun same revision/rule/layer -> idempotent result; interrupted recomputation does not expose half-updated records.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Run shadow comparisons on a copied snapshot, review differences, then switch one rule family at a time. Keep canonical versions available for reproducibility.

## Outside this PR

No new habitat/legal-impact inference, display-geometry analysis, nationwide screening, or unsupported claims of field-verified conditions.

## Agent handoff

> Implement D02 only, after its dependencies are merged. Replace current screening calculations with provenance-versioned PostGIS predicates and explicit incomplete-coverage semantics. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
