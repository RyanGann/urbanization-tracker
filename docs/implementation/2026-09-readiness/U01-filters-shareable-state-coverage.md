# U01 — Make filters complete and map state shareable

Execution status: [plan.json](plan.json), entry `U01`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Usability / G2 |
| Depends on | [P06](P06-vector-overlay-client.md), [P08](P08-viewport-map-client.md), [D01](D01-source-scope-pagination-canaries.md), [U00](U00-immediate-filter-correctness.md) |
| Review | Routine coding agent |
| PR boundary | One filter/state/disclosure UI PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

The default map excludes 500 completed records and public submissions, while selecting no statuses means all. Users cannot share their viewport/filters or tell whether missing geometry reflects incomplete coverage.

## Code to inspect

- [apps/web/src/pages/MapPage.tsx](../../../apps/web/src/pages/MapPage.tsx)
- [apps/web/src/api.ts](../../../apps/web/src/api.ts)
- [apps/web/src/types.ts](../../../apps/web/src/types.ts)
- [apps/web/src/components/DevelopmentMap.tsx](../../../apps/web/src/components/DevelopmentMap.tsx)
- [apps/web/src/styles.css](../../../apps/web/src/styles.css)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Offer all six known statuses and every supported development type, including public_submission. Default to all statuses/types; if a product-specific shortcut hides completed records, label it explicitly and show the hidden count.

2. Represent absent filter parameters as all and an explicit empty selection as none using CONTRACTS.md. Unknown values show a validation message or reset action; never silently broaden the query.

3. Encode validated center/zoom, selected ID, repeated filters and enabled layer IDs in the URL. Initialize once from the URL, update with debounced replaceState, and support browser back/forward without request/render loops. Private watch geometry/email never enters shareable URLs.

4. Show fetched_at/last_success_at, declared pilot scope and complete/partial/stale/unavailable source status. Distinguish total matching records from records loaded in this viewport; link users to source provenance and coverage details.

5. Use catalog IDs/defaults for layers and an accessible legend matching actual source categories. Preserve user choices across catalog refresh; show a clear reason when a layer is not ready or a URL references a removed ID.

6. Add an accessible reset-to-Huntsville action, empty-result recovery and a non-map results list. Use text labels in addition to color; controls remain reachable on narrow screens.

## Acceptance and verification

- [ ] Known completed and approved public-submission fixtures appear under default filters; deselect all returns zero, not all.
- [ ] Copy a map URL into a new live browser context: viewport, filters, selection and layers restore; back/forward behaves correctly.
- [ ] Partial/stale/failed source fixtures produce honest labels without implying absent environmental features.
- [ ] Keyboard-only navigation, 375px width and automated accessibility checks cover filter controls, count updates and focus.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Document the intentional change to inclusive defaults. Existing unparameterized URLs become the complete pilot view; old unsupported parameters receive a recoverable notice.

## Outside this PR

No new source ingestion, generalized GIS query builder, or full visual redesign.

## Agent handoff

> Implement U01 only, after its dependencies are merged. Fix filter semantics/defaults and add shareable, validated map state with truthful coverage and freshness labels. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
