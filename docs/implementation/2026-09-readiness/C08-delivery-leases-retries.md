# C08 — Deliver outbox messages with leases, retries, and clear failure states

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Correctness / G1 |
| Depends on | [C07](C07-publication-watch-matcher.md), [S03](S03-watch-confirmation-unsubscribe.md) |
| Review | Lead review |
| PR boundary | One delivery-worker hardening PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

The current sender scans queued items without a durable claim. Concurrent jobs or crashes can resend, lose progress, or leave ambiguous status.

## Code to inspect

- [apps/api/app/alert_delivery.py](../../../apps/api/app/alert_delivery.py)
- [apps/api/app/phase3_store.py](../../../apps/api/app/phase3_store.py)
- [apps/api/app/models.py](../../../apps/api/app/models.py)
- [apps/api/app/ingestion/cli.py](../../../apps/api/app/ingestion/cli.py)
- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [docs/operations-monitoring.md](../../operations-monitoring.md)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Claim due rows using a short transaction with FOR UPDATE SKIP LOCKED and a lease token/expiry, then send outside the transaction. Final status updates must compare the lease token so an expired worker cannot overwrite a later attempt.

2. Use queued, leased, retry, sent, suppressed and dead states. Default bounded batch 25, finite timeouts, retry delays 1/5/30 minutes then 2/12 hours with jitter, and a maximum attempt count. Enforce configured provider throughput with a shared database-backed send budget so concurrent workers cannot multiply it. Permanent address/provider failures become dead; transient transport failures retry.

3. Recheck subscription state immediately before sending a development alert; suppress pending/unsubscribed watches. Confirmation messages follow their own expiry and resend rules. Validate positive batch limits and honor global ALERT_DELIVERY_ENABLED=false.

4. Use a deterministic Message-ID per outbox item and provider idempotency when available. SMTP is at-least-once: a crash after acceptance but before recording success may duplicate a message. Document that ambiguity; do not claim exactly-once delivery.

5. Expose backlog age, attempt counts, dead/suppressed counts and sanitized failure classes. Provide a dry-run report and authenticated retry of eligible dead messages with an audit record.

6. Consolidate old alert status/count endpoints onto the durable outbox. Do not leave the legacy sender able to process the same messages in parallel.

## Acceptance and verification

- [ ] Two workers compete for the same batch: one lease per row; a crashed worker's lease expires and is retried.
- [ ] Local SMTP accepts, temporarily rejects, permanently rejects and stalls; verify states, attempt budgets, rate limits and cancellation on unsubscribe.
- [ ] Simulate crash before send and after SMTP acceptance; demonstrate recovery and document the duplicate window.
- [ ] No network email is attempted when disabled, and error responses/logs redact recipient, credentials and tokens.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Run dry-run and sink delivery first. Keep real delivery disabled until subscription, retry, unsubscribe and operator-monitoring acceptance pass. Rollback pauses the worker while retaining outbox rows.

## Outside this PR

No external queue service, automatic provider provisioning, or guarantees SMTP cannot provide.

## Agent handoff

> Implement C08 only, after its dependencies are merged. Replace the legacy sender with leased outbox processing and bounded retries; provide explicit crash-recovery evidence and the remaining SMTP ambiguity. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
