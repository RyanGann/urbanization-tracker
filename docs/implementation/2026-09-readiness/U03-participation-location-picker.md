# U03 — Replace shared coordinate inputs with explicit location selection

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Usability / G2 |
| Depends on | [S02](S02-public-input-validation.md), [U02](U02-basemap-record-search.md) |
| Review | Routine with visual review |
| PR boundary | One participation UX PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

Submission and watch forms share a default bounding rectangle, so users can submit the wrong location without intending to select it.

## Code to inspect

- [apps/web/src/pages/ParticipatePage.tsx](../../../apps/web/src/pages/ParticipatePage.tsx)
- [apps/web/src/components/DevelopmentMap.tsx](../../../apps/web/src/components/DevelopmentMap.tsx)
- [apps/web/src/api.ts](../../../apps/web/src/api.ts)
- [apps/web/src/types.ts](../../../apps/web/src/types.ts)
- [apps/web/src/styles.css](../../../apps/web/src/styles.css)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Give each form independent location state initialized to no user selection. Create a small reusable map picker that supports a submission point or rectangle and a watch rectangle; defer arbitrary polygon editing until needed.

2. Require a visible preview and an explicit selected area/point summary before sending. For submissions offer 'Location unknown' as a deliberate choice that sends null and explains reviewer follow-up; never silently supply Huntsville's center.

3. Allow search-assisted map navigation using U02 and an accessible coordinate-entry alternative with bounds validation. A typed coordinate update must redraw the preview and remain separate between forms.

4. Apply S02's area/vertex/body limits client-side for immediate feedback while keeping API validation authoritative. Do not confuse display-simplified geometry with the user's submitted original geometry.

5. Show the submission receipt/review status and S03 pending-confirmation expectation when that API is available. Maintain form values after recoverable errors and prevent accidental duplicate requests.

6. Provide clear remove/reset controls, keyboard focus order and a usable 375px layout without requiring precise map gestures.

## Acceptance and verification

- [ ] Set watch bounds, then submit a point: each API payload retains its own explicit geometry.
- [ ] Submit without choosing a location -> client guidance; explicitly choose unknown -> null staging geometry.
- [ ] Invalid/reversed coordinates, oversized area and server 422/429 responses produce accessible errors without losing the form.
- [ ] Live browser creates a located submission and a watch, then reviewer/API inspection confirms the exact geometries.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Preserve existing API field names where possible. Do not make a previously unlocated record appear located during migration; only new explicit selections create geometry.

## Outside this PR

No paid geocoder, advanced polygon editor, automatic source scraping, or visual assumption that a rectangle is a surveyed boundary.

## Agent handoff

> Implement U03 only, after its dependencies are merged. Implement separate explicit location selection for submissions and watches, including keyboard alternatives and live payload verification. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
