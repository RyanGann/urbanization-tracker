# U04 — Let reviewers validate and correct a candidate location

Execution status: [plan.json](plan.json), entry `U04`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Usability / G1 |
| Depends on | [C05](C05-review-action-policy.md), [S02](S02-public-input-validation.md), [U02](U02-basemap-record-search.md), [C06](C06-publication-events-history.md) |
| Review | Lead review |
| PR boundary | One reviewer geometry-editing PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The steps below define this guide's scope; use its manifest entry and evidence to determine current capability.

## Problem and intended result

Unlocated/low-confidence candidates cannot be safely published from the current review screen, which lacks a geometry correction workflow.

## Code to inspect

- [apps/web/src/pages/ReviewerPage.tsx](../../../apps/web/src/pages/ReviewerPage.tsx)
- [apps/web/src/components/DevelopmentMap.tsx](../../../apps/web/src/components/DevelopmentMap.tsx)
- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)
- [apps/api/app/phase3_store.py](../../../apps/api/app/phase3_store.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Add an authenticated candidate geometry-update endpoint requiring expected_revision, geometry, geometry_source, confidence and a reviewer note. Use S02 validation and C02 transactions; location edits create a new candidate revision/audit entry.

2. Show source document links, current geometry and confidence alongside a map picker. Support point/rectangle placement and validated GeoJSON upload for a complex boundary; do not build a full drawing suite in this PR.

3. Keep original source geometry/provenance for comparison. Label manually drawn bounds as approximate, and require the reviewer to state the source of the correction.

4. Enforce publication prerequisites in the API: valid located geometry, current candidate revision, allowed action and required source/provenance fields. The UI shows exactly which prerequisite remains missing.

5. Approval uses C06's publication service and never mutates the public map before success. A correction to an already published record creates a substantive new version instead of rewriting history.

6. Handle two reviewers editing concurrently with a 409 conflict and side-by-side old/current values; do not automatically replay a stale edit.

## Acceptance and verification

- [ ] Unlocated agenda candidate cannot publish; reviewer adds supported geometry -> approve -> detail/map index/event contain that geometry.
- [ ] Malformed upload, oversize geometry, missing note and stale revision fail without partial edits.
- [ ] Original and edited geometry provenance survive API restart and decision export.
- [ ] Keyboard-only reviewer can locate a point through numeric input and complete approval without map dragging.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Restrict to existing reviewer authentication; use a copied dataset during review. Preserve both prior public versions and raw source geometry.

## Outside this PR

No automatic geocoding, geometry repair without review, source-record mass edits, or enterprise GIS editor.

## Agent handoff

> Implement U04 only, after its dependencies are merged. Add a small revision-checked geometry correction flow and enforce located publication through the real API. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
