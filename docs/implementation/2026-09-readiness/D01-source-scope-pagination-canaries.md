# D01 — Fetch a declared pilot scope completely and report source coverage

Execution status: [plan.json](plan.json), entry `D01`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Data quality / G1 |
| Depends on | [C03](C03-stable-source-identity.md), [T01](T01-real-api-postgis-harness.md) |
| Review | Lead review |
| PR boundary | One ingestion coverage PR across the current ArcGIS connectors; no new sources. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

Development defaults fetch the first 500/2,000 features, while health can still suggest success. The June snapshot is partial; current upstream totals must be measured rather than inferred from those old counts.

## Code to inspect

- [apps/api/app/ingestion/connectors/arcgis.py](../../../apps/api/app/ingestion/connectors/arcgis.py)
- [apps/api/app/ingestion/sources/huntsville.py](../../../apps/api/app/ingestion/sources/huntsville.py)
- [apps/api/app/ingestion/sources/madison_county.py](../../../apps/api/app/ingestion/sources/madison_county.py)
- [apps/api/app/ingestion/pipeline.py](../../../apps/api/app/ingestion/pipeline.py)
- [apps/api/app/source_monitoring.py](../../../apps/api/app/source_monitoring.py)
- [docs/data-sources/huntsville-al.md](../../data-sources/huntsville-al.md)
- [docs/data-sources/madison-county-al.md](../../data-sources/madison-county-al.md)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Version a reviewed Huntsville pilot boundary and a context buffer covering the largest screening threshold. Record source-query spatial relation, CRS, any time window, and boundary checksum. County records are intentionally included only when they intersect this declared scope; show that limitation.

2. Prefer ArcGIS returnIdsOnly followed by stable object-ID batches, deduplicated and reconciled against the scoped ID set. If a service requires offset paging, enforce stable order and test full pages where exceededTransferLimit is absent. Count reconciliation must use the same spatial/temporal query.

3. Apply bounded retries with jitter, timeouts, rate limits and source-specific page sizes. Stream page artifacts to disk/storage; do not assemble every raw layer twice in memory. Abort or label incomplete runs when records fail validation or upstream IDs change during collection.

4. Separate transport status, freshness, and coverage: complete, partial, failed, unknown. Persist expected/fetched/accepted/rejected counts, scope/version, fetched_at and last_success_at. Explicit sample mode may retain a cap but must never claim complete coverage.

5. Add small opt-in live upstream canaries: layer metadata, required fields/CRS, one scoped ID/count query, and at most one small geometry batch per source. Save sanitized diagnostics; never mutate canonical production data or download a whole layer during ordinary CI.

6. Do not activate a failed/partial replacement as a complete environmental snapshot. Retain last-good data and expose both its age and the failed attempt.

## Acceptance and verification

- [ ] Local HTTP source fixture covers multi-page results, missing transfer flag, repeated page, changing IDs, 429/retry, timeout, invalid geometry, complete empty, and partial failure.
- [ ] Real API health exposes accurate coverage after each fixture ingestion and survives restart.
- [ ] Run the opt-in upstream command once with a request cap; record endpoint/field changes as actionable results without assuming today's totals equal June's.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Run a complete scoped refresh into an isolated dataset first and compare source counts/geometry extent. Do not publish newly fetched source data until redistribution and coverage checks are recorded.

## Outside this PR

No statewide/national crawl, inference of environmental absence from incomplete data, or live upstream calls in required unit tests.

## Agent handoff

> Implement D01 only, after its dependencies are merged. Replace arbitrary production caps with bounded complete scoped pagination, explicit coverage health, and a separate low-volume upstream canary suite. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
