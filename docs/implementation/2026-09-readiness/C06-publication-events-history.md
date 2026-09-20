# C06 — Publish canonical changes and durable history in one transaction

Execution status: [plan.json](plan.json), entry `C06`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Correctness / G1 |
| Depends on | [C03](C03-stable-source-identity.md), [C04](C04-agenda-revision-retention.md), [C05](C05-review-action-policy.md), [S02](S02-public-input-validation.md) |
| Review | Lead review |
| PR boundary | One publication service/events PR; matching and mail are separate. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The steps below define this guide's scope; use its manifest entry and evidence to determine current capability.

## Problem and intended result

Publication is split between ingestion and reviewed submissions; source updates generally expose only a current snapshot. Later watches cannot react reliably without a durable change record.

## Code to inspect

- [apps/api/app/models.py](../../../apps/api/app/models.py)
- [apps/api/app/processed_store.py](../../../apps/api/app/processed_store.py)
- [apps/api/app/phase3_store.py](../../../apps/api/app/phase3_store.py)
- [apps/api/app/seed_store.py](../../../apps/api/app/seed_store.py)
- [apps/api/app/ingestion/pipeline.py](../../../apps/api/app/ingestion/pipeline.py)
- [apps/api/app/main.py](../../../apps/api/app/main.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Create a publication service called by every public-record create/update/retract path, including ArcGIS ingestion and reviewer approval. Require S02's geometry validation and explicit located provenance before creating/updating a public record; invalid or unknown-location staging cannot be made durable publication history. Within C02's transaction, resolve existing identity, compare the approved public-content fingerprint, write the canonical row and append its event/version.

2. Add publication_events keyed by event_id and unique(public_id,revision), using string public IDs. Store event kind, before/after public snapshot, changed fields, source/run provenance, occurred_at, notify_eligible and matcher state. Do not attach these to the unused integer DevelopmentRecord scaffold by assumption.

3. Use monotonic per-record revisions under the canonical write lock. An unchanged refresh updates last_checked separately but creates no substantive event. A source geometry/status change creates one event; retries cannot create another revision for the same accepted source observation.

4. Backfill one baseline event per current record with notify_eligible=false and history_available_from clearly stated. Preserve genuine existing history; do not fabricate past transitions or email users about migration.

5. Serve record versions/change logs from the event history plus any explicitly migrated legacy history. Retraction retains a tombstone/reason and removes the current map representation atomically once the map index exists.

6. Provide an internal synchronous projection hook for P07's map index and an asynchronous durable matcher cursor/state for C07. No HTTP callback, in-memory event bus or SMTP operation belongs in this transaction.

## Acceptance and verification

- [ ] Live API: approve one submission -> canonical detail and one version after restart; retry unchanged approval/ingestion -> no duplicate event.
- [ ] Change status and geometry -> the same public_id advances one revision with correct before/after; last_checked-only refresh -> no event.
- [ ] Inject a failure after event insertion -> canonical row and event both roll back.
- [ ] Migration creates baseline history without any delivery-eligible backlog; unauthenticated history excludes raw personal/source payloads.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Add tables before switching writers; backfill under maintenance lock, reconcile record/event counts, then enable the single publication path. Preserve event data on application rollback.

## Outside this PR

No email delivery, map optimization, invented historical changes, or event-sourcing rewrite of every internal collection.

## Agent handoff

> Implement C06 only, after its dependencies are merged. Unify all public writes behind one transactional publication service and durable version log, with idempotent replay and no-op semantics. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
