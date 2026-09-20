# S01 — Patch frontend dependencies and verify map compatibility

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Security / G0 |
| Depends on | None; may start now |
| Review | Routine with visual review |
| PR boundary | One dependency/migration PR; no feature redesign. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

The September audit found a critical MapLibre advisory and moderate router-related advisories. The current fixed attribution did not demonstrate an exploit, but third-party basemaps will introduce a new input surface.

## Code to inspect

- [apps/web/package.json](../../../apps/web/package.json)
- [package-lock.json](../../../package-lock.json)
- [apps/web/src/components/DevelopmentMap.tsx](../../../apps/web/src/components/DevelopmentMap.tsx)
- [apps/web/src/main.tsx](../../../apps/web/src/main.tsx)
- [apps/web/e2e/phase1.spec.ts](../../../apps/web/e2e/phase1.spec.ts)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Re-run the production dependency audit and consult maintainer advisories on the implementation date. The review identified MapLibre 6.4.1 as the first patched version for GHSA-jrc7-96c5-q579; select a currently supported patched release rather than assuming that version remains sufficient.

2. Update the minimum coherent dependency set, lockfile, and required MapLibre/React Router call sites. Read migration notes for the jump from MapLibre 4.7.1. Avoid an unrelated React/Vite/toolchain upgrade unless a required security fix depends on it; explain any extra major version.

3. Keep route-level lazy loading and worker/CSP behavior intact. Sanitize application-created HTML and rely on patched attribution handling; do not work around the advisory by hiding attribution.

4. Capture before/after bundle sizes and inspect point/polygon selection, popup escaping, fit/ease transitions, overlay visibility, attribution links, route reloads, and map cleanup under React StrictMode.

5. Document the production audit result with advisory disposition and exact resolved versions. Any remaining reachable high/critical issue blocks the relevant alpha gate.

## Acceptance and verification

- [ ] Run npm ci, web unit tests, TypeScript, production build, and existing Chromium smoke tests.
- [ ] Exercise the map with both existing local fixture data and a third-party attribution fixture containing unsafe markup; verify no script execution and legitimate attribution remains visible.
- [ ] Open map, detail, participation and reviewer routes directly, then navigate away/back; confirm no duplicate canvas, stale handlers, or worker errors.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Keep package and lockfile changes together. Revert the whole dependency change if compatibility fails; do not ship an unpatched map library with the new basemap.

## Outside this PR

No basemap provider switch, map-data migration, or broad UI restyling.

## Agent handoff

> Implement S01 only, after its dependencies are merged. Patch the vulnerable production packages, make the smallest necessary compatibility edits, and provide audit/build/visual evidence. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
