# C01 explicit data modes evidence

Base: `9ed339bb23c8a4b15c8f7c1f04d8f4cc6c137ff8` (merged T01/S01 main)
Tested commit: `1a147bd846738c828a1a5644c0a5900132a70c1b`

## Final implementation and review

Implementation [PR #18](https://github.com/RyanGann/urbanization-tracker/pull/18) merged at `ee6bc5dd2ae77fa16154fd86294e84514f7caa50`. Its final reviewed head was `821734a944a50d01de2d45754fad109b730e9125`.

The final [GitHub Actions CI run](https://github.com/RyanGann/urbanization-tracker/actions/runs/35487422741) passed. It included readiness-plan validation, API lint and type checking, 73 API tests, web type checking/tests/build, regular and production browser smoke, the T01 real-stack smoke, and the required C01 data-modes scenario.

Eight Codex review threads were resolved before merge. The resulting fixes cover unavailable-state handling and source-health behavior, strict live/demo isolation including direct operational reads and missing-artifact fallback, demo documentation, validation of malformed canonical artifacts, record-detail error semantics, and clearing stale map overlays and selections after a failed refetch. The final source-monitoring compatibility fix is `2d36b78`.

## Real stack

Command: `node scripts/run-integration.mjs --suite api --scenario c01-data-modes`

Passed on September 20, 2026. Manifest: `tmp/integration/2026-09-20T03-09-44-934Z-cc80af9a/manifest.json`. The isolated Compose project `urbanization_t01_ce7488afb48b` finished with `cleanup_result: removed`.

The scenario used the T01 PostGIS Compose stack and real HTTP through its fixed gateway. It verified:

- Initialized empty PostgreSQL returns live/ready metadata, an empty record and GeoJSON collection, and 404 for an unknown detail.
- A seeded PostgreSQL fixture survives a database stop and restart; while stopped, list, detail, and GeoJSON return 503 with `detail.code=data_unavailable` and no seed fallback.
- Missing, empty, and corrupt live artifact collections distinguish uninitialized, ready-empty, and unavailable states.
- Explicit demo reports `data_mode=demo`, returns demo-only records, and does not mix the live fixture. The first request after switching to demo is an authenticated reviewer read, before any catalog request. A real live public submission is excluded there; a following demo-created submission stays memory-only and is absent after returning to the same live Postgres backend.
- Browser checks against the real internal API distinguish empty, unavailable with no map features or record rows, and labelled demo data.

Fixture SHA-256: `932eacb03655a3dee1a2838abf9ddf8d5dfa44f744482408611b61a2561bbee2`.

Generated empty artifact SHA-256: `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570`.

Generated corrupt artifact SHA-256: `ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356`.

## Ordinary checks

`npm run typecheck:web` passed after the C01 client and browser test changes.

The API production image built successfully from the C01 source. A direct attempt to run pytest in that runtime image was not applicable because its deliberately minimal runtime lock does not install pytest; the test attempt was cleaned with `docker compose down --volumes --remove-orphans`. A locked test-container run of `pytest tests/test_data_modes.py tests/test_api.py tests/test_processed_store.py tests/test_phase3_store.py` passed 31 tests with two deprecation warnings. The later full lint/mypy/pytest shell command returned exit 0, but its complete per-check output was not retained; the separate required GitHub CI checks provide the final auditable full-suite result. The C01 real-stack scenario is now also an explicit required CI step.

## Limits

No deployment, real SMTP delivery, saved dataset mutation, or external source fetch was performed. The scenario used generated files only beneath its integration artifact directory and removed its Compose resources on completion.