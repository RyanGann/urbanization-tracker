# C09 — Merge confirmed duplicates without losing URLs or provenance

Execution status: [plan.json](plan.json), entry `C09`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Correctness / G1 |
| Depends on | [C06](C06-publication-events-history.md), [U04](U04-reviewer-geometry-correction.md), [C07](C07-publication-watch-matcher.md) |
| Review | Lead review |
| PR boundary | One manual merge preview/apply PR; no automatic matching engine. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The steps below define this guide's scope; use its manifest entry and evidence to determine current capability.

## Problem and intended result

Duplicate candidates exist, but there is no safe reviewer merge preserving source identity, public links and version history.

## Code to inspect

- [apps/api/app/phase3_store.py](../../../apps/api/app/phase3_store.py)
- [apps/api/app/models.py](../../../apps/api/app/models.py)
- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)
- [apps/web/src/pages/ReviewerPage.tsx](../../../apps/web/src/pages/ReviewerPage.tsx)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Add an authenticated merge preview for two explicit candidate/public IDs. Show competing fields/geometries, source identities, public links, event history and downstream watch effects. Require a chosen surviving public_id, expected revisions and a reason.

2. Apply the accepted field selection in one C02/C06 transaction. Keep all source identities attached to the survivor, preserve source-specific observations and append merge provenance; do not overwrite conflicting source facts silently. Persist the ownership of selected fields and any reviewer geometry override so a later source refresh updates observations without silently undoing the reviewed merge; clearing an override requires an explicit audited action.

3. Store a permanent alias from the retired public ID to the survivor. Public detail requests resolve/redirect consistently, search/map excludes the duplicate, and old versions remain inspectable with clear merged-into metadata.

4. Record a substantive merge event with explicit notification policy: no burst of baseline/history alerts. Preserve watch-area geometry/filters and existing outbox idempotency keys; historical or queued links to the retired ID resolve through its alias. Future notifications match the survivor through C07's ordinary spatial/filter rules, including its before-state rules for leaving an area. Do not invent automatic follow-record subscriptions or move a user's watch area because records merged.

5. Reject circular aliases, merge-to-self, stale revisions and already-merged conflicting requests. Include a dry-run JSON export and an audit trail sufficient to support a deliberate corrective split later.

6. Update only the existing duplicate review panel; evidence gathering remains manual.

## Acceptance and verification

- [ ] Merge two records -> one map feature, both old URLs resolve, all source links/history remain, and future source refreshes update the survivor.
- [ ] Concurrent source refresh/reviewer merge yields a safe conflict or serial outcome without losing fields.
- [ ] Retry apply -> one merge event, no duplicate aliases or alerts; invalid cycles fail.
- [ ] A failed intermediate write rolls back alias, record, event and index together. Watch-area definitions remain unchanged, and historical/queued notification links still resolve after a successful merge.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Use dry-run previews and a disposable database first. A merge is not undone by dropping audit rows; document an explicit corrective procedure and retain pre-merge snapshots.

## Outside this PR

No fuzzy auto-merge, bulk unattended merge, deletion of source documents, or unsupported claim that similarly named projects are identical.

## Agent handoff

> Implement C09 only, after its dependencies are merged. Build manual duplicate preview/apply with durable aliases and atomic history preservation; keep matching decisions with reviewers. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
