# S03 — Confirm watch subscriptions and make unsubscribe links work

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Security / G1 |
| Depends on | [C07](C07-publication-watch-matcher.md), [S02](S02-public-input-validation.md) |
| Review | Routine with lead review |
| PR boundary | One subscription lifecycle API/UI PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

Watch creation accepts arbitrary recipients without verified opt-in. Existing unsubscribe links append an API path to PUBLIC_BASE_URL, which is the separate static website origin.

## Code to inspect

- [apps/api/app/phase3_store.py](../../../apps/api/app/phase3_store.py)
- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)
- [apps/api/app/config.py](../../../apps/api/app/config.py)
- [apps/api/app/alert_delivery.py](../../../apps/api/app/alert_delivery.py)
- [apps/web/src/pages/ParticipatePage.tsx](../../../apps/web/src/pages/ParticipatePage.tsx)
- [apps/web/src/main.tsx](../../../apps/web/src/main.tsx)
- [apps/web/src/api.ts](../../../apps/web/src/api.ts)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Introduce pending_confirmation, active and unsubscribed subscription states. Creating a watch gives a generic receipt and queues a confirmation message; it never activates delivery immediately. Legacy subscriptions without proof of confirmation remain pending.

2. Generate cryptographically random, purpose-bound, expiring confirmation tokens and store only hashes in the subscription/token table. Put the minimum short-lived delivery secret in the restricted outbox only when needed to send, exclude it from logs/backups exported to reviewers, and clear it after sending/expiry.

3. Implement /watch/confirm and /watch/unsubscribe web routes, using the configured API base. Email links target the web origin; the rendered page performs an explicit POST confirmation/unsubscribe action. GET previews must not mutate state, so mail security scanners cannot silently confirm or unsubscribe.

4. Make confirmation single-use and idempotent for the same completed action; invalidate superseded tokens. Use 24-hour confirmation expiry, a resend cooldown and configurable daily per-recipient limits, plus S02's shared request controls.

5. Unsubscribe immediately suppresses queued matching mail and remains effective across restart. Do not expose whether arbitrary emails are subscribed. Offer a clear success/expired-link state and an accessible resend path.

6. Handle old API unsubscribe URLs with an explicit compatibility landing/redirect policy; do not keep a silent GET mutation as the main flow. Redact tokens from application/access logs and use a restrictive Referrer-Policy on token pages.

## Acceptance and verification

- [ ] With a local SMTP sink: create -> pending -> no change alerts; follow confirmation landing without POST -> still pending; POST -> active.
- [ ] Expired/reused/wrong-purpose tokens fail safely; generic receipts do not reveal recipient existence; resend quotas work across workers.
- [ ] Click the exact generated absolute link in a web+API split-origin live test; unsubscribe suppresses an already queued message.
- [ ] URL reloads, screen-reader labels and keyboard-only completion work on narrow screens.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Do not email all legacy users automatically during migration. Document the pending-state transition and test with local recipients only until O03's controlled verification.

## Outside this PR

No paid email-provider selection, real invitation campaign, or claim of delivered mail before C08.

## Agent handoff

> Implement S03 only, after its dependencies are merged. Build verified opt-in and usable cross-origin confirmation/unsubscribe routes, using the outbox and local mail sink. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
