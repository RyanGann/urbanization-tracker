# P05 — Serve bounded, cached environmental vector tiles

Execution status: [plan.json](plan.json), entry `P05`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Performance / G1 |
| Depends on | [P04](P04-environmental-display-derivatives.md) |
| Review | Lead review |
| PR boundary | One read-only tile API PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The [performance plan](PERFORMANCE.md) fixes the architecture, budgets and measurement protocol for this PR. The steps below define this guide's scope; use its manifest entry and evidence to determine current capability.

## Problem and intended result

The browser needs only visible geometry at its current scale. A versioned spatial tile endpoint removes repeated whole-layer transfers and allows safe caching.

## Code to inspect

- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)
- [apps/api/app/config.py](../../../apps/api/app/config.py)
- [apps/api/app/db.py](../../../apps/api/app/db.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Implement GET /api/map/layers/{layer_id}/tiles/{version}/{z}/{x}/{y}.pbf with the exact version and error semantics in CONTRACTS.md. Validate layer/version, integer coordinates, zoom bounds and service extent before running SQL; parameterize all values and allowlist any selected table/band.

2. Use indexed EPSG:3857 display parts intersecting the buffered tile envelope, ST_AsMVTGeom with extent 4096/buffer 64, and ST_AsMVT with source-layer 'environment'. Query the expanded envelope by buffer/extent margin. Avoid transforming the indexed column in the WHERE clause.

3. Return only public feature ID/category attributes needed for styling. Set vector-tile Content-Type, CORS and immutable cache headers for versioned successful responses; add ETag/conditional GET and correct Vary: Accept-Encoding. Define ETag semantics for the actual served representation.

4. Return an empty valid tile for a known ready version with no intersecting features. Unknown version is 404, deliberately expired version 410, unavailable dependency/build 503; failures are never cached as valid empty geometry.

5. Bound statement time, response size and any process cache (initial total 64 MiB). Over-budget tiles fail visibly with diagnostics and trigger preprocessing/LOD tuning; do not randomly drop features. Support cancellation and avoid copying the whole layer into Python.

6. Capture tile timing/size/cache-hit metrics without logging user locations at full precision. Add readiness checks for required indexes and active versions.

## Acceptance and verification

- [ ] Decode tiles and verify fixed source-layer, feature IDs, clipped geometry, holes and adjacent tile continuity.
- [ ] Exercise invalid/negative/out-of-range coordinates, unknown/expired versions, empty tiles, database failure, ETag 304 and compressed/uncompressed variants.
- [ ] Run dense-tile and selective-query benchmarks from P01; meet payload/SQL budgets without canonical geometry changes.
- [ ] Memory stays bounded across many unique requests; API never opens the legacy overlay artifact.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Expose the endpoint before P06 switches the client. Keep old version URLs valid during rollout and use active-pointer rollback rather than overwriting cached bytes.

## Outside this PR

No standalone tile server/CDN provisioning, live dynamic simplification, public raw source payloads, or replacing 503 with empty 200 responses.

## Agent handoff

> Implement P05 only, after its dependencies are merged. Implement the versioned MVT endpoint with indexed spatial queries, explicit errors and representation-correct caching; supply decoded-tile and performance evidence. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
