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
The catalog is generated during ingestion. Existing deployments now run an
idempotent offline upgrade before the API release:

```text
alembic upgrade head
python -m app.ingestion.cli upgrade-map-layer-catalog
```

The API's `render.yaml` `preDeployCommand` runs these commands in Render's separate
release process, before API startup ([Render deployment documentation](https://render.com/docs/deploys)).
The upgrade acquires the C02 mutation lock and rechecks the catalog, validates and
preserves any existing catalog (including ready tile metadata), and creates only a
missing catalog from populated legacy overlay rows. PostgreSQL projects metadata
and feature counts; full geometry never crosses into the release process. The
database may inspect the legacy JSON, once per missing catalog, under C02's five
second statement timeout. A timeout or corrupt catalog fails the release without
replacing existing metadata. No source network request occurs.
All legacy PostgreSQL catalog writers (ingestion, explicit backfill, and artifact
migration) use the same C02 lock and singleton item upsert. Callers already owning
a transaction must write through their existing unit of work instead of opening
an independent transaction through the convenience writer.

For an existing installation, release the API and verify `/api/map/layers` before
releasing the catalog-dependent web build. The two Render services' automatic
deploys are independent and do not guarantee that order; use sequential manual
releases for this initial upgrade. No deployment was performed during this work.

Absent legacy overlay rows have no initialization marker, so they remain
uninitialized even if source health exists. A new installation must initialize
its source catalog through ingestion, or an operator who has verified a known
empty processed collection can use the explicit compatibility command:

```text
python -m app.ingestion.cli backfill-map-layer-catalog
```

That command is compatibility recovery for an existing processed store: it may
read the legacy collection offline, does not fetch a source, and writes only the
compact singleton. Unlike the idempotent release upgrade, this explicit command
rebuilds an existing catalog and should be used only for deliberate recovery.
Removing the singleton returns the controlled unavailable state until the next
ingestion or offline upgrade/backfill. P03/C03 will migrate the ingestion writer into
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

Result: Ruff passed; mypy found no issues in 33 modules; pytest passed 28 tests
(two upstream TestClient deprecation warnings). The focused tests cover the compact
response bound, ETag revalidation/change, live/demo mode mismatch, missing and
malformed catalogs, no-store failures, real Huntsville layer IDs, no HTTP-path call
to the legacy reader, and the explicit offline projection path. It also proves that
equal fetched/reported counts remain `unknown`, observed truncation is `partial`,
and failed ingestion is `failed`; D01 owns scoped completeness reconciliation.

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

### September 22 upgrade and U00 integration verification

After rebasing onto U00 merge `fbd5ad8a5e6d4af474d7eb07a4abbcb8b655c046`,
web type checking and both runner measurement tests passed. A clean installed
Python 3.12 project copy with the locked dependencies passed Ruff, mypy (34
modules), and 14 focused catalog/CLI/ingestion tests. An initial check copied an
ignored stale build directory and imported old packaged code; that attempt failed
and is not counted as validation.

The same isolated catalog-development command passed again in run
`2026-09-22T13-30-31-553Z-bd83bfd9`, project `urbanization_t01_f609f7e3114b`.
It recorded base SHA `bf02c9e71233a9ad2fa4baacc470ebabe127c092` with a dirty
working tree containing the upgrade fix, fixture SHA
`cc7114c31fa8dbce0374279ccc4b4eabb8bebf021513719781c8ba7312c1edc3`,
and successful exact-project cleanup. The seed step exercised the real
PostgreSQL metadata projection, absent/failed-health initialization boundary,
idempotent replay, and preservation of a valid ready catalog and its revision.
The browser again completed both cold loads and physical record selections;
environmental usable-context completeness remains false. Raw manifests, runtime
image digests, commands, browser results and screenshots are retained in the
ignored run directory. Final remote CI also checks U00 filters and C02 concurrency.

The catalog-writer race found in subsequent review was reproduced as a lock
serialization regression in the real stack. Run
`2026-09-22T13-39-46-756Z-aeb4e52a` passed with exact-project cleanup, using the
same fixture checksum and base `daf469a8944ad9ccaabcf67ff94d8fe95f50fc2b` plus
uncommitted locking changes. The regression observed the convenience writer
waiting in PostgreSQL `pg_locks`, then completing after release, and the upgrade
preserving its result. The final helper placement also covers artifact migration
writers. Locked lint, mypy and 14 focused tests were rerun successfully after that
placement change; final CI exercises the exact committed path.

### Merged verification

[PR #22](https://github.com/RyanGann/urbanization-tracker/pull/22) merged as
`87c2f74676154fddd140eda953c23317f8cb2e2d`. Codex completed a clean review of
runtime head `b1c3b54bf3627add099997ea8bb20d8912e923e0`; all five prior review
threads were addressed and resolved. The final commit
`d84efde0a84eb261e75991b82d4e5664e95cae5d` corrected integration-driver argument
passing for synthetic reviewer tokens beginning with a hyphen. The lead reviewed
that narrow harness change, which also forces the edge case on every run.
[Final CI run](https://github.com/RyanGann/urbanization-tracker/actions/runs/35736371168)
passed before the expected-head squash merge.

This completes catalog delivery and the development-only precheck. Environmental
layers remain disabled until P06 supplies usable context; this is not a passing
P01 performance-budget result or deployment-readiness claim.
