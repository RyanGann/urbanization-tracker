# S02 — Validate geometry and limit public write abuse

Execution status: [plan.json](plan.json), entry `S02`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Security / G1 |
| Depends on | [C02](C02-transactional-store-foundation.md) |
| Review | Lead review |
| PR boundary | One public API input/limits PR. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. The steps below define this guide's scope; use its manifest entry and evidence to determine current capability.

## Problem and intended result

Public inputs accept weakly validated geometry, and missing locations can become a city-center point. Public write endpoints have no application-level request controls.

## Code to inspect

- [apps/api/app/schemas.py](../../../apps/api/app/schemas.py)
- [apps/api/app/ingestion/geometry.py](../../../apps/api/app/ingestion/geometry.py)
- [apps/api/app/phase3_store.py](../../../apps/api/app/phase3_store.py)
- [apps/api/app/main.py](../../../apps/api/app/main.py)
- [apps/api/app/config.py](../../../apps/api/app/config.py)
- [docs/privacy-safety-checklist.md](../../privacy-safety-checklist.md)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Add a shared geometry validator using PostGIS validity for polygon topology and explicit JSON structure checks. Reject NaN/infinity, out-of-range longitude/latitude, unsupported geometry types, unclosed rings, excessive nesting/vertices and invalid self-intersections. Do not silently repair a user's geometry.

2. For watches accept Polygon/MultiPolygon, at most 2,000 vertices and a configurable pilot maximum area initially 2,500 km², measured geodesically. For submissions accept Point/Polygon/MultiPolygon or explicitly unknown location. An unknown location stays null in staging and blocks publication.

3. Apply a 256 KiB request-body ceiling before JSON decoding on public writes, text length limits, strict email parsing and an allowlist of supported watch filters. Accept only http/https source links; do not fetch arbitrary submitted URLs from the API.

4. Add configurable database-backed public-write quotas suitable for multiple API workers. Initial defaults: 10 submissions and 10 watch requests per hour per trusted client address, plus stricter per-recipient confirmation limits in S03. Store short-lived keyed hashes, not raw client addresses.

5. Trust proxy forwarding headers only from explicitly configured proxies. Return 413/422/429 with accessible client messages and Retry-After for throttling. Record aggregate rejection reasons without logging emails, tokens, private notes or complete request bodies.

6. Ensure API receipts and public detail schemas use allowlists; reviewer-only contact data never leaks through map properties, source_fields, versions or logs.

## Acceptance and verification

- [ ] Real HTTP malformed/oversize geometry, bow-tie polygon, hole, multipolygon, NaN, bad URL scheme and unknown filters produce deterministic errors.
- [ ] A no-location submission creates an unlocated staged record, not a fake public marker.
- [ ] Two API workers share quotas; spoofed X-Forwarded-For cannot bypass them; allowed requests still persist correctly.
- [ ] A fixture containing emails/private fields is absent from public map, detail, versions, receipts and sanitized logs.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

Publish request limits and keep local fixtures within them. Existing invalid records require a diagnostic/quarantine report, not destructive cleanup. Review limits after real pilot usage.

## Outside this PR

No CAPTCHA vendor, anonymous contact enrichment, automatic geocoding, or automatic geometry repair.

## Agent handoff

> Implement S02 only, after its dependencies are merged. Implement explicit input limits and privacy-safe validation for public writes, with real HTTP and multi-worker tests. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
