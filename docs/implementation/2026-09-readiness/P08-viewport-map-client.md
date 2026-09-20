# P08 — Query developments by viewport and avoid redundant map work

Execution status: [plan.json](plan.json), entry `P08`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Performance / G2 |
| Depends on | [P07](P07-bounded-development-map-api.md), [S01](S01-frontend-dependency-update.md) |
| Review | Routine coding agent |
| PR boundary | One development map/list client PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The [performance plan](PERFORMANCE.md) fixes the architecture, budgets and measurement protocol for this PR. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

Every filter change currently loads full records and map effects repeat source updates. The selected full object can become stale, and list rendering scales with the entire dataset.

## Code to inspect

- [apps/web/src/api.ts](../../../apps/web/src/api.ts)
- [apps/web/src/types.ts](../../../apps/web/src/types.ts)
- [apps/web/src/pages/MapPage.tsx](../../../apps/web/src/pages/MapPage.tsx)
- [apps/web/src/components/DevelopmentMap.tsx](../../../apps/web/src/components/DevelopmentMap.tsx)
- [apps/web/src/utils/records.ts](../../../apps/web/src/utils/records.ts)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Replace the map's full-record query with the bounded viewport endpoint. Debounce moveend/filter requests by 200 ms, include all filters/bbox/zoom in query keys, and pass TanStack Query's AbortSignal through fetch. Cancel old requests and ignore late responses.

2. Use conservative enclosing bbox quantization only if it improves cache reuse; never shrink the visible query extent. Restart pagination on filters/viewport/dataset revision change. Accumulate at most 2,000 features and show an explicit zoom/filter prompt when more remain.

3. Keep only selectedPublicId as selection state. Fetch full detail on selection and handle missing/retracted/outside-filter records explicitly. Use stable feature IDs and feature-state for highlighting; clicking a record must not resend unchanged source geometry.

4. Update MapLibre setData only when the feature collection changes. Separate camera/selection, visibility, source data and initialization effects. Keep expensive derived feature collections memoized and dispose listeners cleanly.

5. Paginate the visible result list in 50-row pages with at most 100 mounted rows; show returned versus total matching counts and loading-more state. Preserve keyboard focus and selection as results change.

6. Use distinct initial loading, background fetching, empty, truncated and unavailable UI. Keep last-good results during a same-scope refresh with an explicit updating/stale label; do not leave old results under new filter labels.

## Acceptance and verification

- [ ] Rapid pan/filter requests arriving out of order never replace the latest viewport; aborted fetches do not show errors.
- [ ] Selecting/toggling/hovering does not call setData for unchanged records or rebuild environmental sources.
- [ ] A selected record removed by filter/retraction gets a clear state; direct detail links still work.
- [ ] Large fixture stays within client/DOM budgets and the live map's visible result count matches the API scope.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Switch only the map route; detail/reviewer views continue using their purpose-specific endpoints. Preserve a straightforward rollback to the preceding client while the old APIs remain.

## Outside this PR

No new virtual-list framework unless measured necessary, broad state-management rewrite, or hiding omitted results.

## Agent handoff

> Implement P08 only, after its dependencies are merged. Implement bounded viewport fetching, cancellation, stable selection and isolated map effects; prove stale responses and toggles cannot cause data/render churn. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
