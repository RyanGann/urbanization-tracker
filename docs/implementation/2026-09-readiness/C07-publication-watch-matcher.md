# C07 — Generate future-change watch alerts through a durable outbox

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Correctness / G1 |
| Depends on | [C06](C06-publication-events-history.md), [S02](S02-public-input-validation.md) |
| Review | Lead review |
| PR boundary | One matcher/outbox PR; delivery stays disabled. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

A watch created before a later matching publication receives no queued alert. Bounding boxes also overmatch irregular geometry, and current alert IDs do not distinguish revisions.

## Code to inspect

- [apps/api/app/models.py](../../../apps/api/app/models.py)
- [apps/api/app/phase3_store.py](../../../apps/api/app/phase3_store.py)
- [apps/api/app/ingestion/cli.py](../../../apps/api/app/ingestion/cli.py)
- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Create a watch_alert_outbox with a unique idempotency key and the lifecycle in CONTRACTS.md. A development notification key is (watch_id,event_id,channel); confirmation jobs use a separate message_kind and request key. Introduce subscription state and confirmed_at storage here; migrate unverified legacy subscriptions to pending_confirmation. C08 will deliver fixture-generated messages through the local sink, and S03 will add the public confirmation lifecycle.

2. Add a bounded CLI matcher that claims unprocessed publication events safely and considers only currently active subscriptions with a non-null confirmed_at <= event.occurred_at. Creation time alone is insufficient: a pending watch confirmed after an event must never receive that historical event when a delayed matcher runs. S03 will activate verified subscriptions; preexisting unverified subscriptions remain pending and cannot receive mail.

3. Match public after-state geometry with exact PostGIS ST_Intersects and any explicitly supported distance rule using original geometry/geography, not bounding boxes alone. Apply the same validated status/type filters as the watch contract. A retraction or a change leaving a watched area may notify only watches that previously matched that record; label why.

4. Insert matching outbox rows and mark the publication event processed in the same transaction. Handle zero matches as a completed event. Use a bounded batch and short transactions; reruns and concurrent workers must be safe.

5. Treat creation-time matches as a preview count, not a flood of historical emails. Baseline migration events and context-only recalculations are not delivery eligible by default. Show queued versus delivered counts separately.

6. Expose matcher backlog age/count and failure diagnostics to authenticated operations status. Keep user content/email out of logs.

## Acceptance and verification

- [ ] Create an active test watch -> publish later matching record through HTTP -> one outbox row; restart/replay/two concurrent matchers -> still one.
- [ ] Update substantive content -> one new revision alert; last_checked-only update -> none; baseline migration -> none.
- [ ] A polygon hole/bbox false positive does not match; edge intersection does. Filter mismatch, unsubscribed and unconfirmed watches do not queue. A watch pending when an event occurs, then confirmed before delayed matching, still queues no historical alert on initial match or replay.
- [ ] Failure between inserting alerts and marking event processed rolls back; retry completes without loss.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Backfill confirmed state only for explicitly verified test subscriptions; production legacy rows remain unverified. Dry-run counts before enabling the scheduled matcher, and leave outbound mail off.

## Outside this PR

No SMTP, exactly-once email claim, external message broker, or automatic notification of the entire historical dataset.

## Agent handoff

> Implement C07 only, after its dependencies are merged. Implement the durable publication-event matcher and outbox, proving one logical notification per watch and record revision across retries. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
