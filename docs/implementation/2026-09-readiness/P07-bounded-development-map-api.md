# P07 — Add an indexed viewport query for development summaries

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Performance / G1 |
| Depends on | [C06](C06-publication-events-history.md), [U00](U00-immediate-filter-correctness.md) |
| Review | Lead review |
| PR boundary | One derived map-index/API PR; the canonical public record remains unchanged. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The [performance plan](PERFORMANCE.md) fixes the architecture, budgets and measurement protocol for this PR. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

The map fetches all full records, including descriptions, source fields and geometry. Bounding the response requires an indexed spatial read path, not slicing a fully loaded Python collection.

## Code to inspect

- [apps/api/app/models.py](../../../apps/api/app/models.py)
- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)
- [apps/api/app/processed_store.py](../../../apps/api/app/processed_store.py)
- [apps/api/app/phase3_store.py](../../../apps/api/app/phase3_store.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Add development_map_index keyed by string public_id with publication_revision, safe summary fields, indexed original geometry/centroid and bounded display geometry. This is a derived projection of existing canonical records, not a second source of truth.

2. Add an index-state record initially not ready, then install synchronous upsert/delete in every active C06 publication writer before exposing the read API. For this pilot, run backfill and canonical-ID/revision reconciliation under C02's canonical mutation lock (or explicitly pause all writers); only then mark the index ready in that same transaction. Older writers that lack the projection hook must be stopped before cutover. A concurrent publication must either precede the locked backfill or wait and commit through the installed hook afterward. Failed/timed-out backfill keeps readiness false and is retryable. Missing or incompatible index state returns 503; never fall back to an unbounded full scan.

3. Implement GET /api/map/developments using CONTRACTS.md: required bbox/zoom, shared repeated filter names, default limit 500/max 1,000, stable cursor, dataset revision, total matching count, returned count, next_cursor and truncation reason.

4. Use indexed geometry intersection, allowlisted filters, deterministic public_id ordering and a revision-bound cursor. Return 409 dataset_changed if the dataset advances between pages; the client restarts. Validate malformed bounds/cursors/unknown filters with 422.

5. Use summary-only GeoJSON properties and geometry appropriate to zoom; points/centroids at broad scale and bounded simplified display footprints at close zoom. Do not attach source_fields, full descriptions or private inputs. Enforce <=512 KiB decoded per page by stopping on a stable record boundary and issuing a cursor; simplify oversized single display footprints further or use an explicitly labelled centroid.

6. Keep full geometry/detail available through the record-detail endpoint, using keyed canonical item lookup rather than copying every collection to find one ID. Add a bounded title/public-ID search query over the same index for U02; no third-party geocoder is required.

## Acceptance and verification

- [ ] Real API filtering/empty selections, viewport edges, holes, pagination, cursor tampering, concurrent publication and index rebuild are covered.
- [ ] Publish/update/retract -> detail, index and revision change atomically; failed transaction leaves all unchanged. Use two database connections and a barrier to force publication during backfill, then prove the ready index has every current ID/revision and no retracted record; no write may fall between backfill and hook installation.
- [ ] A large synthetic fixture proves selective index use and response budget; private/source payload fields never appear.
- [ ] Exact total and displayed counts are distinguished; a page-size byte cap never silently loses a record.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Build the index in shadow, reconcile counts/IDs, then expose the new endpoint. Do not remove existing detail APIs or switch clients before P08.

## Outside this PR

No wholesale normalized-record migration, full-data client filtering, clustering service, or development vector tiles unless measurements later justify them.

## Agent handoff

> Implement P07 only, after its dependencies are merged. Build a transactional derived spatial index and a bounded summary API with stable pagination and truthful counts. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
