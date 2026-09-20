# P01 — Establish a reproducible map performance baseline

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Performance / G0 |
| Depends on | [T01](T01-real-api-postgis-harness.md) |
| Review | Routine coding agent |
| PR boundary | One measurement/fixture PR; no optimization yet. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The [performance plan](PERFORMANCE.md) fixes the architecture, budgets and measurement protocol for this PR. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

The review measured a 128,934,218-byte overlay response taking 39.22 seconds, but that single run was not controlled. Timing and payload budgets need a reproducible fixture and an honest definition of a useful map.

## Code to inspect

- [apps/web/playwright.config.ts](../../../apps/web/playwright.config.ts)
- [apps/web/src/pages/MapPage.tsx](../../../apps/web/src/pages/MapPage.tsx)
- [apps/web/src/components/DevelopmentMap.tsx](../../../apps/web/src/components/DevelopmentMap.tsx)
- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [Makefile](../../../Makefile)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Implement the benchmark protocol and fixture specification in PERFORMANCE.md. Generate deterministic development records and large environmental polygons, including holes, multipolygons and dense tile boundaries. Commit the generator/seed/checksum, not a hundred-megabyte licensed dataset.

2. Add benchmark-only instrumentation for catalog received, visible record data received, first selectable map feature rendered, initial list ready and enabled overlay ready. A blank canvas or data-feature-count attribute is not proof of successful rendering.

3. Capture HTTP encoded/decoded sizes, request counts, server timings, browser long tasks, bundle transfer, API/container peak memory and relevant SQL plans. Separate application data from basemap/glyph/sprite traffic.

4. Run ten fresh-browser cold loads and a warm interaction scenario with pan, zoom, filter, selection and overlay toggles; run enough API requests for a meaningful p95. Record browser build, CPU/network profile, viewport, database size, cache state and application SHA.

5. Add an optional local snapshot benchmark reading only a disposable copy of the June artifacts. Never rewrite working data or commit raw private/source payloads. Clearly distinguish controlled synthetic metrics from this realistic snapshot observation.

6. Create a baseline JSON/report artifact and command that future performance PRs can reuse without manually changing test code.

## Acceptance and verification

- [ ] Benchmark fails its functional precheck if a record cannot be selected, the API is mocked, or an enabled overlay has not rendered.
- [ ] Generated fixtures reproduce the same checksums and geometry cases; fixture generation stays outside timed measurements.
- [ ] Run twice and explain variation; report encoded and decoded bytes separately. No performance target is marked passed solely by avoiding all real data.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Measurement code should be test-only or low-cost marks behind a build flag. The legacy application is expected to fail the proposed budgets initially; record failures without making unrelated CI permanently red.

## Outside this PR

No production behavior change, screenshot-only performance inference, or hand-tuned benchmark dataset hiding dense geometry.

## Agent handoff

> Implement P01 only, after its dependencies are merged. Implement PERFORMANCE.md's reproducible benchmark and baseline artifacts. Measure before changing behavior. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
