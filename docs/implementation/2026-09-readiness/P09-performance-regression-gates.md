# P09 — Enforce map payload and performance budgets in CI

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Performance / G2 |
| Depends on | [P06](P06-vector-overlay-client.md), [P08](P08-viewport-map-client.md), [U01](U01-filters-shareable-state-coverage.md), [U02](U02-basemap-record-search.md) |
| Review | Routine coding agent |
| PR boundary | One performance-regression CI PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The [performance plan](PERFORMANCE.md) fixes the architecture, budgets and measurement protocol for this PR. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

Current smoke tests use a tiny mocked feature, and the existing test-performance target does not measure a real large-data browser session.

## Code to inspect

- [apps/web/playwright.config.ts](../../../apps/web/playwright.config.ts)
- [.github/workflows/ci.yml](../../../.github/workflows/ci.yml)
- [Makefile](../../../Makefile)
- [apps/api/tests/test_phase4_hardening.py](../../../apps/api/tests/test_phase4_hardening.py)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Convert P01's baseline harness into the gates specified in PERFORMANCE.md. Required PR checks enforce structural/payload budgets, no bulk-overlay traffic, bounded DOM/features, real-API functional correctness and representative spatial-index availability.

2. Add a reproducible dedicated/reference profile for timing comparisons. Run ten cold browser loads and 100 API requests per scenario, report distributions and cache state, and retain traces/HAR/timing JSON on failure.

3. Keep timing gates tolerant of runner variance and separate from deterministic byte/count assertions. Establish a measured baseline on the agreed reference profile before making a new threshold required; do not silently weaken targets until current code passes.

4. Cover desktop/mobile initial view, dense environmental tile, repeated pan/zoom/toggle, filtered results, selected detail, stale/error recovery and catalog version switch. Include basemap overhead separately and in a total transfer report.

5. Report bundle size and route chunks so non-map pages do not acquire MapLibre accidentally. Check API memory after repeated map requests and browser memory trend as diagnostics, avoiding brittle heap assertions on shared runners.

6. Update the performance report with achieved, missed and unmeasured targets. Document the exact reproduction command for a cheaper agent and the fixture checksum.

## Acceptance and verification

- [ ] Intentionally reintroduce an eager legacy overlay request or oversized map property; required CI fails.
- [ ] Intentionally replace the spatial viewport predicate with a full scan on a large fixture; the targeted plan/performance check detects it without assuming every tiny table uses an index.
- [ ] Functional assertions catch an empty canvas or missing enabled overlay even if timings are fast.
- [ ] A transient external basemap outage is distinguished from application performance and is not reported as a passed ready-map run.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Introduce checks with one recorded reference result, then require deterministic gates immediately. Timing misses require an owner/explanation and block the public-map gate until resolved or explicitly revised.

## Outside this PR

No benchmark gaming, nightly automatic cloud load tests, production traffic generation, or pretending a mocked response proves live performance.

## Agent handoff

> Implement P09 only, after its dependencies are merged. Turn the shared benchmark into meaningful CI gates and publish before/after metrics with functional rendering evidence. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
