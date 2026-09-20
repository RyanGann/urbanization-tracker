# P03 — Import versioned environmental geometry into indexed PostGIS storage

Execution status: [plan.json](plan.json), entry `P03`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Performance / G1 |
| Depends on | [T01](T01-real-api-postgis-harness.md), [C02](C02-transactional-store-foundation.md), [P02](P02-layer-catalog-startup-relief.md) |
| Review | Lead review |
| PR boundary | One additive schema/import PR; no tile endpoint or display simplification. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The [performance plan](PERFORMANCE.md) fixes the architecture, budgets and measurement protocol for this PR. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

Environmental geometry lives in a large collection artifact and is repeatedly copied/validated. Existing EnvironmentalLayer/EnvironmentalFeature tables are scaffolded but not the active read model.

## Code to inspect

- [apps/api/app/models.py](../../../apps/api/app/models.py)
- [apps/api/app/ingestion/pipeline.py](../../../apps/api/app/ingestion/pipeline.py)
- [apps/api/app/ingestion/cli.py](../../../apps/api/app/ingestion/cli.py)
- [apps/api/app/processed_store.py](../../../apps/api/app/processed_store.py)
- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Extend the existing environmental tables using new Alembic revisions: stable layer key and immutable version identity, source/scope/checksum metadata, feature identity unique within a version, import status and count/extent statistics. Use the schema direction in CONTRACTS.md rather than creating a competing canonical environmental store.

2. Keep canonical feature geometry in EPSG:4326 at original accepted precision and preserve source attributes through an explicit public/private allowlist. Add and verify GiST indexes; avoid duplicate indexes if GeoAlchemy already creates one.

3. Add a streaming/chunked importer for existing saved overlays and new ingestion output. Prefer a streaming JSON reader for legacy collections, and record rejected/invalid features explicitly. Missing feature IDs require deterministic source-aware import keys or quarantine, never unstable list positions.

4. Hash source content, declared scope and importer schema version into an immutable data version. Reimporting identical input is idempotent. Large parsing/upload work happens outside the short activation transaction.

5. Write versions in loading/validated states, expose import progress and metadata in the catalog, and retain the previous active version on failure. P04 owns ready display derivatives and atomic activation; P03 must not publish an incomplete layer.

6. Add dry-run validation and a backfill report showing original/accepted/rejected counts, geometry bounds, source attribution, precision and database size.

## Acceptance and verification

- [ ] Import synthetic holes/multipolygons and a copied real snapshot; canonical geometry is unchanged in coordinates/precision except explicitly quarantined invalid input.
- [ ] Replay identical import -> no duplicate features/version; fail mid-import -> prior active catalog still resolves.
- [ ] Unique source IDs, spatial index presence, bounded importer memory and restart/resume behavior are verified against PostGIS.
- [ ] Invalid geometry and incomplete source coverage remain visible; no repair or rejected feature silently changes environmental completeness.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Additive schema and shadow import first. Keep raw originals, record a checksum report, and do not remove legacy artifacts until O03 recovery verification.

## Outside this PR

No environmental screening changes, geometry simplification, full-table destructive replacement, or live data publication.

## Agent handoff

> Implement P03 only, after its dependencies are merged. Build versioned canonical environmental import into the existing spatial model, preserving original geometry and proving idempotency/failure isolation. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
