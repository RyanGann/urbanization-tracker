# C02 — Introduce shared transactions and safe item mutations

Execution status: [plan.json](plan.json), entry `C02`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Correctness / G1 |
| Depends on | [T01](T01-real-api-postgis-harness.md), [C01](C01-explicit-data-modes.md) |
| Review | Lead review |
| PR boundary | One storage foundation PR; migrate callers in the explicitly dependent PRs. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The steps below define this guide's scope; use its manifest entry and evidence to determine current capability.

## Problem and intended result

Current store functions read collections and later replace all database rows in an independent transaction. Concurrent writers can overwrite each other's work.

## Code to inspect

- [apps/api/app/db.py](../../../apps/api/app/db.py)
- [apps/api/app/processed_store.py](../../../apps/api/app/processed_store.py)
- [apps/api/app/phase3_store.py](../../../apps/api/app/phase3_store.py)
- [apps/api/app/models.py](../../../apps/api/app/models.py)
- [apps/api/tests/test_processed_store.py](../../../apps/api/tests/test_processed_store.py)
- [apps/api/tests/test_phase3_store.py](../../../apps/api/tests/test_phase3_store.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Add a unit-of-work helper accepting a shared SQLAlchemy Session, with item get/upsert/delete operations against existing generic collection tables. Keep unique(collection_name,item_id) constraints and preserve deterministic read order.

2. For this small pilot, serialize canonical/operational mutations with one documented PostgreSQL transaction advisory lock, acquired before reading affected state. Use a fixed namespace/key from CONTRACTS.md. Prefer this simple correctness boundary to multiple competing lock schemes.

3. Ensure nested store functions use the caller's transaction and do not commit independently. Bulk snapshot replacement is permitted only for explicit maintenance/import under the same lock, never ordinary submission/review writes. Network fetches, PDF processing, uploads, and SMTP occur outside the transaction.

4. Convert public-submission creation and watch creation to item mutations in this PR, proving multi-row atomicity. Inventory every remaining write entry point and mark which following PR migrates it; keep the alpha gate closed until that list is empty.

5. Artifact/demo mode remains single-writer only, using atomic per-file replacement and explicit limitations. Do not claim it offers PostgreSQL's multi-collection transaction guarantees.

## Acceptance and verification

- [ ] Two concurrent HTTP submissions persist both receipts and their staged rows after restart.
- [ ] Inject a failure between dependent writes; verify all rollback and no partial receipt remains.
- [ ] Hold the canonical lock in one connection and verify a second mutation waits/ times out cleanly; unrelated reads remain available.
- [ ] Check unique-key conflict handling and migration/import preservation without replacing unrelated items.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Additive helper first; migrated paths must not call legacy independent-transaction writers. Document lock timeouts and record transaction duration. Do not mix new and old writers in a public deployment.

## Outside this PR

No full rewrite into every unused normalized model, distributed lock service, queue broker, or claims of complete concurrency coverage yet.

## Agent handoff

> Implement C02 only, after its dependencies are merged. Implement the unit of work, item operations, and the two creation paths. Include a remaining-writer checklist and real two-connection race tests. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
