# P02 — compact layer catalog and startup relief

P02 replaces the map's automatic whole-overlay download with a persisted metadata
catalog. It is an intermediate delivery step: environmental geometry and tiles are
deliberately unavailable until P06, and this evidence does not claim the P01
usable-context baseline has passed.

## Contract and recovery

`GET /api/map/layers` reads only the `map_layer_catalog` processed singleton. It
returns validated live or demo metadata with a content-derived ETag and
`Cache-Control: public, max-age=60, must-revalidate`. A missing, malformed,
content-hash-mismatched, or cross-mode catalog is `503 data_unavailable` with
`Cache-Control: no-store`.
The catalog is generated during ingestion and can be reconstructed only with the
explicit offline command:

```text
python -m app.ingestion.cli backfill-map-layer-catalog
```

That command is compatibility recovery for an existing processed store: it may
read the legacy collection offline, does not fetch a source, and writes only the
compact singleton. Removing the singleton returns the controlled unavailable state
until the next ingestion or offline backfill. P03/C03 will migrate this writer into
the durable transactional inventory; P06 will consume ready tile URLs.

## Validation

The locked Python check used a disposable Python 3.12 container, the checked-in
`requirements.lock`, and an installed project copy:

```text
python -m pip install --disable-pip-version-check -r requirements.lock
python -m pip install --disable-pip-version-check --no-deps .
ruff check app tests/test_map_layer_catalog.py
mypy app
pytest tests/test_map_layer_catalog.py tests/test_api.py tests/test_ingestion_pipeline.py
```

Result: Ruff passed; mypy found no issues in 31 modules; pytest passed 27 tests
(two upstream TestClient deprecation warnings). The focused tests cover the compact
response bound, ETag revalidation/change, live/demo mode mismatch, missing and
malformed catalogs, no-store failures, real Huntsville layer IDs, no HTTP-path call
to the legacy reader, and the explicit offline projection path.

Web type validation passed:

```text
npm run typecheck:web
```

The isolated real-stack command used only P01's generated public synthetic A
fixture; it did not refresh sources or write a saved dataset:

```text
node scripts/run-integration.mjs --suite performance --scenario catalog-development --profile desktop --smoke
```

Run `2026-09-20T04-21-45-808Z-e61fdcb6` passed and removed its exact Compose
project `urbanization_t01_25c8bb38f039`. The generated fixture SHA-256 was
`cc7114c31fa8dbce0374279ccc4b4eabb8bebf021513719781c8ba7312c1edc3`.
Its browser report recorded two cold loads and two physical selection interactions,
all eight API samples successful, zero requests to `/api/environmental-overlays`,
and a 706-byte decoded `/api/map/layers` response. Each cold load verified that a
catalog layer was unchecked and disabled with the accessible preparation message.
It retained initial and selected screenshots locally in the ignored run artifact.
`usable_context_complete` remains false and `context_ready_ms` null by design.

The runner manifest records the pre-commit application SHA
`d6aeb1b7beffbb703946b80cd6227a185fb32b4b` and `working_tree_dirty: true`; the
run includes the P02 implementation changes validated above. The final PR commit
will retain this exact artifact reference and rerun all required remote CI.
