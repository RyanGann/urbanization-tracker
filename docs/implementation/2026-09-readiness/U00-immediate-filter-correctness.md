# U00 — Make current map filters show the intended records

Execution status: [plan.json](plan.json), entry `U00`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Usability / G1 |
| Depends on | [C01](C01-explicit-data-modes.md) |
| Review | Routine coding agent |
| PR boundary | One small correctness PR on current endpoints; do this before the larger map refactor. |

Read the [shared contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md). Endpoint changes below are proposed work.

## Problem and intended result

The current default filters omit completed county records and approved public submissions. Deselecting everything accidentally requests all records. These problems can be fixed before the spatial performance work lands.

## Code to inspect

- [apps/web/src/pages/MapPage.tsx](../../../apps/web/src/pages/MapPage.tsx)
- [apps/web/src/api.ts](../../../apps/web/src/api.ts)
- [apps/web/src/types.ts](../../../apps/web/src/types.ts)
- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [apps/api/app/seed_store.py](../../../apps/api/app/seed_store.py)
- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)

## Implementation steps

1. Show all six valid statuses and include public_submission in development types. Default to all supported statuses/types; preserve source labels and a clear result count.

2. Implement the shared absent=all and explicit none=zero filter contract on existing list/GeoJSON endpoints and their web callers. A literal none token cannot be combined with other values; unsupported values return 422.

3. Keep the options and query serializer in one reusable module so P07/P08 use identical semantics later. Avoid using an empty array as an ambiguous synonym for both none and all.

4. Handle zero matches and reset filters accessibly. Do not add URL state, new map data architecture or source ingestion in this PR.

5. Add a real API/browser fixture containing completed, proposed and published public-submission records. Demonstrate default visibility and every filter combination that previously hid them.

## Acceptance and verification

- [ ] Default map query returns every eligible published fixture, including completed and public_submission records.
- [ ] Deselect all statuses/types -> zero; reset -> all; an explicit subset returns only that subset.
- [ ] Live list and GeoJSON endpoints use the same filter semantics; invalid/mixed-none tokens fail clearly.
- [ ] Existing unit/Chromium checks pass with updated expectations, and no backend seed fallback returns.
- [ ] Retain exact commands, commit SHA, fixture checksum and real API/browser results.

## Rollout and recovery

This is a deliberate correction to default visibility. Update any existing tests that encoded the old omission; preserve the original endpoint shapes for other callers.

## Outside this PR

No tile API, viewport index, source refresh, complete filter redesign or arbitrary new development classifications.

## Agent handoff

> Implement U00 only after C01 merges. Fix current filter defaults and empty-selection semantics now, with real API evidence; leave larger map changes to their separate PRs. Return the focused diff, acceptance evidence and any remaining risks. Do not deploy or change the saved data.
