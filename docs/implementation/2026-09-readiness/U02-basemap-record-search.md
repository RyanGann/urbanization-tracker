# U02 — Add a contextual basemap and local record search

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Usability / G2 |
| Depends on | [P08](P08-viewport-map-client.md), [S01](S01-frontend-dependency-update.md) |
| Review | Routine with visual review |
| PR boundary | One map orientation/search PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

The current background-only style has no streets/place labels, and users cannot find a development by name or ID.

## Code to inspect

- [apps/web/src/components/DevelopmentMap.tsx](../../../apps/web/src/components/DevelopmentMap.tsx)
- [apps/web/src/pages/MapPage.tsx](../../../apps/web/src/pages/MapPage.tsx)
- [apps/web/src/api.ts](../../../apps/web/src/api.ts)
- [apps/web/src/styles.css](../../../apps/web/src/styles.css)
- [.env.example](../../../.env.example)
- [docs/deployment.md](../../deployment.md)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Add a configurable VITE_MAP_STYLE_URL and a development default using OpenFreeMap's documented Liberty style, subject to current attribution/service review. Preserve provider and source attribution. The final hosted provider choice is recorded in O04; do not create paid accounts or embed secret tokens.

2. Keep application overlays independent from basemap source/layer IDs. Restore them after style changes and choose a readable layer order; protect against third-party style errors using S01's patched renderer.

3. Provide debounced, keyboard-accessible search over P07's bounded local title/public-ID endpoint, maximum 20 results. Selecting a result fetches its detail, centers the map and highlights it without resetting filters silently.

4. Label this as development search, not universal address search. A typed street address may match an indexed record address only if that public field is deliberately included; no automatic external geocoder or unreviewed location-data sharing.

5. Handle offline/provider failure visibly while keeping records/list/attribution usable. Include loading, no-results, query-error and selected-result-outside-filter states.

6. Record basemap tiles/glyphs/sprites separately in performance evidence, and test narrow screens, pointer/keyboard interaction and contrast against wetlands/floodplain fills.

## Acceptance and verification

- [ ] Direct map load shows recognizable streets/place labels and correct attribution with actual record selection.
- [ ] Search keyboard arrows/Enter/Escape, empty/short query, accented title, unknown ID and canceled stale query are covered.
- [ ] Simulate style/tile failure and style reload; app layers and selection recover without duplicate sources.
- [ ] Run S01 compatibility and P01 interaction benchmark to quantify added external traffic.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Keep the style URL configurable and provide a documented fallback. Public hosting cannot proceed until provider attribution/use terms are recorded; local development need not wait on a paid-provider decision.

## Outside this PR

No global geocoding, satellite imagery procurement, new search service, or God’s Eye View migration.

## Agent handoff

> Implement U02 only, after its dependencies are merged. Add an attributed configurable basemap and bounded local development search, with failure handling and keyboard support. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
