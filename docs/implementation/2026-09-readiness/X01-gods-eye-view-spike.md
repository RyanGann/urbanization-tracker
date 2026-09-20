# X01 — Evaluate God’s Eye View with one bounded integration experiment

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Optional experiment / Optional |
| Depends on | [O03](O03-restricted-alpha-rehearsal.md), [P09](P09-performance-regression-gates.md) |
| Review | Lead review |
| PR boundary | Separate experimental branch; maximum five working days. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

A 3D base may help communicate landscape context, but changing viewers does not solve data correctness or oversized payloads. The existing assessment favors preserving this backend and provenance model.

## Code to inspect

- [docs/reviews/2026-09-19-gods-eye-view-assessment.md](../../reviews/2026-09-19-gods-eye-view-assessment.md)
- [docs/architecture.md](../../architecture.md)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Pin and inspect the current original bilawalsidhu/gods-eye-view repository/license/security posture on the experiment date. Use an isolated codex/ branch or worktree; preserve the production React/MapLibre app and its working preview.

2. Connect only one pilot development dataset and one environmental layer through the existing bounded API contracts. Record any format/conversion adapter required by Cesium; do not assume MapLibre MVT or React components are drop-in compatible.

3. Demonstrate selection -> existing detail/provenance, source attribution, camera navigation and a return to the accessible 2D view. Use public/synthetic data and no unreviewed live intelligence feeds or paid credentials.

4. Measure initial useful view, transfer/memory, low-end/mobile behavior, keyboard navigation, data freshness/error display and operating cost against P09's reference scenario.

5. List reusable upstream modules, maintenance/fork costs, integration gaps and code-versus-data licensing boundaries. Avoid treating popularity as evidence of stability.

6. Produce screenshots or a local demo plus a go/no-go report: retain 2D, add optional 3D, or justify a broader migration with measured user benefit. Stop at the time box if the adapter alone consumes it.

## Acceptance and verification

- [ ] One record and environmental context load from the actual project API, with working provenance navigation.
- [ ] Comparable P09 data/profile measurements and mobile/accessibility limitations are documented.
- [ ] No production configuration, source data or default map route is replaced.
- [ ] The experiment can be discarded without losing any canonical data or implemented pilot capability.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

A demo and recommendation only. Any production 3D work requires a separately reviewed implementation sequence after the evidence is available.

## Outside this PR

No wholesale rewrite, importing unrelated surveillance feeds, bypassing tile budgets or claiming a demo is deployment-ready.

## Agent handoff

> Implement X01 only, after its dependencies are merged. Run the bounded optional-viewer experiment, measure it against the improved 2D map, and recommend whether any integration is worth continuing. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
