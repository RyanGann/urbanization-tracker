# C01 — Distinguish live data, demo fixtures, empty collections, and unavailable stores

Status: **Planned; no application implementation in this guide.** Baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Correctness / G0 |
| Depends on | [T01](T01-real-api-postgis-harness.md) |
| Review | Routine coding agent |
| PR boundary | One API/configuration/UI state PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

An authoritative empty list currently falls through to seed records. A missing or failed live store must never turn into invented developments.

## Code to inspect

- [apps/api/app/config.py](../../../apps/api/app/config.py)
- [apps/api/app/seed_store.py](../../../apps/api/app/seed_store.py)
- [apps/api/app/processed_store.py](../../../apps/api/app/processed_store.py)
- [apps/api/app/phase3_store.py](../../../apps/api/app/phase3_store.py)
- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [apps/web/src/api.ts](../../../apps/web/src/api.ts)
- [apps/web/src/pages/MapPage.tsx](../../../apps/web/src/pages/MapPage.tsx)
- [.env.example](../../../.env.example)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Add DATA_MODE=live|demo, default live. Demo fixtures are available only when explicitly selected and are visibly labelled. Keep the choice independent of postgres versus artifact storage.

2. Introduce explicit collection-read states: available with zero-or-more items, missing/not initialized, and failed. Remove truthiness-based fallback from record lists, details, maps, staged records, overlays, and health paths. An initialized empty database returns an empty collection.

3. Use the error contract in CONTRACTS.md: unavailable required canonical storage is 503 with a stable error code; unknown record in an available store is 404. Do not turn decoding/database failures into empty successful responses.

4. Return data_mode and dataset availability/freshness in a small metadata response. Update map loading, empty, unavailable, and demo states to be distinct, accessible, and actionable; preserve last-good data with an explicit stale indication only when a last-good snapshot exists.

5. Update local setup and tests to select demo mode explicitly. Hosted preflight must reject demo mode once O02 lands; add a focused guard now if the existing preflight makes that small.

## Acceptance and verification

- [ ] Real API: initialized empty postgres -> zero records; missing artifact in live mode -> 503; valid empty artifact -> zero records; malformed artifact -> 503; explicit demo -> labelled fixtures.
- [ ] Stop the test database and assert no seed record appears in any public map/detail response; restore it and verify recovery.
- [ ] Browser live tests distinguish loading from empty and unavailable, and never show a development marker after a live read failure.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Existing local installations that relied on implicit seed data must set DATA_MODE=demo. Record this as a deliberate behavior change; preserve original artifacts.

## Outside this PR

No source refresh, tile delivery, or catch-all exception suppression.

## Agent handoff

> Implement C01 only, after its dependencies are merged. Remove implicit seed fallback everywhere, add explicit mode and availability semantics, and prove them through the real API. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
