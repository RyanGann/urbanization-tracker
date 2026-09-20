# O03 — Rehearse migration, recovery, and resident/reviewer workflows

Execution status: [plan.json](plan.json), entry `O03`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Operations / G3 |
| Depends on | [C08](C08-delivery-leases-retries.md), [C09](C09-manual-duplicate-resolution.md), [U03](U03-participation-location-picker.md), [D02](D02-authoritative-spatial-screening.md), [P09](P09-performance-regression-gates.md), [O02](O02-deployment-guardrails.md), [O04](O04-release-data-use-decisions.md), [D01](D01-source-scope-pagination-canaries.md) |
| Review | Lead review |
| PR boundary | One acceptance-runbook and evidence PR; fix discovered defects in focused follow-ups. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

Successful unit tests and hosting configuration do not establish a dependable alpha. Persistence, source refresh, real UI journeys and recovery need an end-to-end rehearsal.

## Code to inspect

- [docs/deployment.md](../../deployment.md)
- [docs/operations-monitoring.md](../../operations-monitoring.md)
- [scripts/backup-postgres.sh](../../../scripts/backup-postgres.sh)
- [docs/releases/v0.1-alpha.md](../../releases/v0.1-alpha.md)
- [docs/next-steps.md](../../next-steps.md)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Run the acceptance matrix in TESTING.md against an isolated release-candidate stack with a copied dataset and verified artifact storage. Record commit, image/dependency versions, migration head, fixture/source snapshot hashes and configuration with secrets redacted.

2. Rehearse empty-database bootstrap and existing-data migration, including identity mapping, publication baselines, environmental import, map-index rebuild and safe feature flags. Record counts before/after and unresolved quarantine cases.

3. Repeat ingestion with unchanged then changed fixtures; run reviewer correction/approval/rejection, duplicate merge, public record discovery, watch confirmation, later publication, matching and local-sink delivery. Check the actual generated unsubscribe link.

4. Back up database plus manifests, restore into a second isolated database, retrieve raw artifacts, and verify record IDs/history/review states/active versions/subscriptions/outbox. Do not restore over the working preview or an unrelated Postgres instance.

5. Perform desktop/mobile and keyboard-only resident/reviewer sessions, plus dependency, live-API, upstream canary and performance checks. A declared source outage can be disclosed; fabricated completeness, lost writes or broken opt-out cannot.

6. Produce a concise go/no-go record and restricted-alpha rollout/rollback commands. Separate completed rehearsal from any future real deployment or real recipient send; retain owner decisions and monitoring responsibilities.

## Acceptance and verification

- [ ] All G0–G2 evidence is present, with no unresolved critical correctness/security failure.
- [ ] Restore proves usable application behavior, not merely pg_restore exit status; compare stable identities, source artifacts and event/outbox state.
- [ ] Document rollback without destroying newer writes: pause writers, retain schema/data, restore only to a separate target until an explicit cutover.
- [ ] One independent reviewer can repeat the resident/reviewer acceptance checklist from the runbook.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Prefer an invite-only alpha with a reviewed snapshot, ingestion disabled initially and local/sink mail until an explicitly controlled delivery check. Record the actual hostname only when verified.

## Outside this PR

No automatic production deployment, real invitation mailing, broad geographic expansion or claiming checks passed without retained evidence.

## Agent handoff

> Implement O03 only, after its dependencies are merged. Run and document a complete isolated alpha rehearsal and recovery test; return an evidence-based go/no-go decision and concrete remaining defects. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
