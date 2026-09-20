# C05 — Make review actions explicit, durable, and revision checked

Execution status: [plan.json](plan.json), entry `C05`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Correctness / G1 |
| Depends on | [C02](C02-transactional-store-foundation.md), [C04](C04-agenda-revision-retention.md) |
| Review | Routine with lead review |
| PR boundary | One review API/UI policy PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

Processed ArcGIS rows appear actionable in the reviewer queue, but requests return 404. Review notes and stale-client decisions also need a durable, explicit contract.

## Code to inspect

- [apps/api/app/seed_store.py](../../../apps/api/app/seed_store.py)
- [apps/api/app/phase3_store.py](../../../apps/api/app/phase3_store.py)
- [apps/api/app/processed_store.py](../../../apps/api/app/processed_store.py)
- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)
- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [apps/web/src/pages/ReviewerPage.tsx](../../../apps/web/src/pages/ReviewerPage.tsx)
- [apps/web/src/api.ts](../../../apps/web/src/api.ts)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Resolve staged IDs across processed and operational stores through one repository adapter. Return origin, revision, allowed_actions, review notes/history and an actionability reason in the reviewer schema.

2. For this pilot, validated automatically published ArcGIS rows are read-only audit entries. Return allowed_actions=[] and a visible explanation; known read-only actions return 409 review_not_actionable, not 404. Failed/invalid ingested candidates remain quarantined rather than automatically published.

3. For manual agenda/submission candidates, accept expected_revision with each decision; under the C02 transaction verify it, persist actor/decision/notes/time, and increment revision. A stale revision returns 409 without changing data.

4. Define legal transitions explicitly. Rejecting a new candidate revision must not delete an older published record. Retraction is a separate authenticated action with a required reason, finalized through C06 when available.

5. Update the UI to show provenance, actionable state and conflict recovery. Disable unavailable controls; after a stale-decision response reload and show what changed, without automatically replaying the action.

6. Round-trip notes and revision history through authenticated decision export/import. Validate imports and report conflicts instead of overwriting newer decisions.

## Acceptance and verification

- [ ] The actual processed staged ID resolves and explains read-only status; action returns the documented 409.
- [ ] Two reviewers submit conflicting decisions for one revision: one succeeds, one gets 409; both see the durable final state after restart.
- [ ] Reject/replay/import cannot erase notes or an older published snapshot. Unknown IDs remain 404.
- [ ] Unauthenticated reviewer reads/writes fail when configured; user-facing endpoints never expose reviewer contact details.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Deploy schema and client together or temporarily allow the old client only in explicit local demo mode. Live review writes require revision tokens after migration.

## Outside this PR

No geometry editor, fuzzy merge UI, role-management product, or hidden mutation of already published ArcGIS records.

## Agent handoff

> Implement C05 only, after its dependencies are merged. Repair staged lookup and action affordances, enforce optimistic concurrency, and persist a review audit trail with real API tests. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
