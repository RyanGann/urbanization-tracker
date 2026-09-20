# C03 — Preserve source identity and merge ingestion batches safely

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Correctness / G1 |
| Depends on | [C02](C02-transactional-store-foundation.md) |
| Review | Lead review |
| PR boundary | One source identity and canonical batch-merge PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

Several current public IDs include mutable names/statuses; a status change can appear as a new development. Batch writes infer source membership from returned records and cannot safely distinguish a complete empty result from a failed or partial fetch.

## Code to inspect

- [apps/api/app/ingestion/normalize.py](../../../apps/api/app/ingestion/normalize.py)
- [apps/api/app/ingestion/pipeline.py](../../../apps/api/app/ingestion/pipeline.py)
- [apps/api/app/processed_store.py](../../../apps/api/app/processed_store.py)
- [apps/api/app/models.py](../../../apps/api/app/models.py)
- [apps/api/alembic/versions/20260521_0003_processed_collection_items.py](../../../apps/api/alembic/versions/20260521_0003_processed_collection_items.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Create an identity registry mapping (source_key, source_record_id) to the existing public_id, with unique constraints. Use authoritative source identifiers, preserving their string representation; keep old public IDs as canonical IDs or explicit aliases. Do not rename published URLs merely to adopt a new scheme.

2. Backfill from saved source fields in a dry-run report. Ambiguous/missing keys are quarantined for review; never guess by title/location alone or hash every mutable property into identity. Report collisions before applying an atomic migration.

3. Normalize using the registry and preserve first discovery time. Define the public-content fingerprint in CONTRACTS.md; date_last_checked and ingestion timestamps do not constitute a substantive update.

4. Replace whole-collection ingestion writes with a batch merge under the C02 transaction. Pass source_key, explicit scope, run_id, coverage outcome, and observations separately from the row array, including for a zero-row result. Until D01's scoped count reconciliation is implemented, every legacy/capped production fetch must report unknown or partial coverage, never complete; an omitted coverage value defaults to unknown. A successful HTTP response or reaching the configured row cap cannot establish completeness.

5. Never retire records from failed/partial observations. For a complete scoped result, mark previously observed missing records as source_missing with provenance; retain their published history and do not infer cancelled/completed status. Use an explicit later review/retraction workflow.

6. Expose a small publication-writer seam accepting before/after canonical records; C06 will attach events. Do not introduce temporary competing alert logic.

## Acceptance and verification

- [ ] Replay identical data -> same IDs and first discovery dates; change status/name -> same ID, new content fingerprint; change only checked time -> unchanged fingerprint.
- [ ] Missing ID, duplicate ID and ambiguous legacy backfill produce diagnostics and no silent merging.
- [ ] Concurrent ingestion and submission retain both; failed/partial/complete-empty source runs have distinct, verified outcomes. Current capped fetches and omitted coverage default to partial/unknown and never mark missing records source_missing; only explicitly proven complete test observations may exercise that transition before D01 lands.
- [ ] Existing bookmarked record URLs continue resolving after the identity migration.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Make a copied database backup and a dry-run identity report before any migration. Add a new Alembic revision rather than editing the referenced existing migration. Preserve a mapping export for recovery.

## Outside this PR

No fuzzy duplicate merge, source pagination redesign, publication outbox, or historical event fabrication.

## Agent handoff

> Implement C03 only, after its dependencies are merged. Stabilize identity and source-aware batch merging while preserving every existing public URL. Report migration ambiguities rather than resolving them heuristically. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
