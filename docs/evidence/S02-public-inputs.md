# S02 — Public input, privacy and shared quota evidence

Implemented September 22–24, 2026. This report covers S02; it does not establish deployment readiness. Operator configuration and recovery are in [public input limits](../security/public-input-limits.md).

## Implemented behavior

Public submissions/watches now have a streamed-byte 256 KiB pre-JSON ceiling, UTF-8/depth limits, strict geometry/email/URL/filter validation, privacy-safe errors and fixed rejection reason logs. Live PostgreSQL validates topology/geodesic area through PostGIS and shares atomic hashed-address quotas across workers. Demo/artifact mode remains isolated. Unknown location remains null and blocks publication. Public receipts/current records/map/history use explicit allowlists; private notes never become a public submission description.

The participation form submits unknown location explicitly until U03 supplies an independent picker, exposes safe API limit messages, and preserves its form values after failure. [Final 390px screenshot](S02/participation-mobile.png) was inspected for readable location/error messages and form layout.

## Clean committed real-stack acceptance

S02's four commits were rebased onto merged C03 and the latest documentation-only main commit `4923c4b`. The final dependency-integrated code head `31b066cdaa4af5047e7cff3bfe6df1db75299f49` passed a clean `input-limits` run, `2026-09-24T04-48-42-605Z-ca0532ed`, with committed acceptance JSON SHA256 `ae65d5dd6a596c39687393d1b7e8b2aaf99040b33b03f48b596f04c3369c64d2`. Its project `urbanization_t01_b7b65d320c8a` was removed. At the same code head, C03's `c03-source-identity` real-stack regression passed in run `2026-09-24T04-50-28-446Z-f44a86dd`, with result SHA256 `8e49c1c16e0278d9c0955edfce80eb805c5b38d8d9e273474ee0ef746f964f8d` and project `urbanization_t01_326f2a284250` removed. Both manifests record `working_tree_dirty: false`, `outcome: passed` and `cleanup_result: removed`. The S02 migration is revision `20260922_0005`; it was not applied to the user's saved snapshot. These local runs do not replace the final PR-head CI and review gates.

```text
node scripts/run-integration.mjs --suite api --scenario input-limits
```

Run `2026-09-24T04-48-42-605Z-ca0532ed`, project `urbanization_t01_b7b65d320c8a`: **passed**, working tree clean, cleanup removed the exact labelled resources. The synthetic base fixture SHA256 is `932eacb03655a3dee1a2838abf9ddf8d5dfa44f744482408611b61a2561bbee2`. The committed [acceptance report](S02/acceptance.json) SHA256 is `ae65d5dd6a596c39687393d1b7e8b2aaf99040b33b03f48b596f04c3369c64d2`.

Observed through real HTTP and PostgreSQL:

- Oversized normal/chunked requests return 413. Excessively nested/UTF-16/invalid-UTF-8 JSON, huge integers, NaN, booleans, extra dimensions, out-of-range coordinates, unsafe URL schemes, malformed emails and unsupported filters return 422 without input echoes.
- Bow-tie and invalid-hole polygons fail; a valid hole and multipolygon succeed. PostGIS and isolated Shapely/pyproj agree. 2,499 km² succeeds and 2,501 km² fails; measured backend area differences were about 0.00003 m², within the asserted 1 m² tolerance.
- A tip without geometry persists as null; ordinary approval and imported approval return 409. A located tip publishes without its private notes/contact. Synthetic contact, token and note fields planted in internal canonical/version dictionaries are absent from list, map, detail, history and receipts.
- Two Uvicorn workers (PIDs 21 and 22) started. For **each** public route, 20 concurrent clients with distinct forged X-Forwarded-For headers produced exactly 10 successes and 10 responses with 429/Retry-After. The database contained exactly two route counters at 10 attempts, with 64-character keyed hashes. The same quotas remained exhausted after API restart.
- [Sanitized startup/rejection excerpts](S02/worker-rejections.log) retain process evidence and fixed reason codes only. Private sentinels were absent from the complete service log. No production diagnostic endpoint was added.

Schema: `20260922_0005`. Actual runtime: Docker Engine 29.8.0, Python 3.12.14, Node 22.23.2; PostGIS 3.4.3/GEOS 3.9.0/PROJ 7.2.1 in the isolated PostgreSQL image. Local validation dependencies are pinned in both lockfiles.

## Regressions and UI checks

```text
node scripts/run-integration.mjs --suite concurrency
```

Run `2026-09-22T13-55-01-876Z-2352332d` at the same clean implementation commit: **passed**, cleanup removed. Both simultaneous submissions/watches, initial alerts, unrelated rows, injected rollback, lock timeout/recovery and restart persistence remain correct. Its result SHA256 is `deddd5fa2b449f843a3813aae7c1acf924e1572cb6b47a2b8db3d9989dc0a700`. Existing synthetic watch boxes were narrowed to stay below the new real pilot area limit while still covering their fixtures.

Other executed checks:

- At the rebased S02 code head, locked Python 3.12 container `ruff check .`, `mypy app` (42 source files), and `PYTHONPATH=/src/apps/api pytest -q` all passed: 141 API tests, with two upstream deprecation warnings. The readiness-plan validator passed.
- On the rebased code, web typecheck, six web tests and production build passed. Build still reports the existing large-map-chunk warning; S02 does not claim a performance budget improvement.
- The 390×844 Playwright 1.60 Chromium test previously passed at the earlier committed S02 head; it verifies the actual form sends null geometry and displays the server's 429 message. A final Windows Node 20 rerun failed during Playwright runner initialization before collecting any tests (`test() called here`), so the final PR's Linux Node 22 browser CI is required evidence. Full UI smoke and other live scenarios remain PR gates.

The initial exploratory real run was dirty and is superseded by the clean run above. The user's saved snapshot, preview and unrelated database were not used or changed. No external source refresh, delivery or deployment occurred.

## Remaining integration/release boundaries

The additive quota table should remain on application rollback; dropping it resets active counters. An upgrade through 0005 was exercised in the disposable stack. Expired hashed counters are physically cleaned on subsequent writes, so idle stores may retain expired rows until activity resumes. Fixed-hour windows and process-local demo/artifact limitations are documented.

The generated Render secret is configured, but trusted ingress networks must be verified during deployment rehearsal; without them, users behind one proxy share its conservative quota bucket. C05/C06 still own transactional revision-checked publication, U04 owns reviewer location editing, and S03 owns confirmation/recipient limits. These later tasks must preserve S02's null-location and privacy rules.
