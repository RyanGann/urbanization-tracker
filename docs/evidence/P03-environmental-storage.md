# P03 environmental storage evidence and operating guide

P03 stores immutable shadow environmental versions in PostGIS. It does not activate layers, simplify original geometry, implement tiles, or satisfy the final P01 usable-context performance baseline. P04 owns derivatives and activation; P06 owns enabled environmental controls.

## Storage and import contract

Migration `20260922_0006` follows `20260922_0005`. It adds nullable version/provenance/count fields to existing environmental layers and marks all old features `import_managed=false`. Legacy duplicate and missing source IDs remain unchanged. A partial unique index and nonblank ID check apply only to managed features. The old schema already creates two equivalent geometry GiST indexes (`idx_environmental_features_geometry` and `ix_environmental_features_geometry`). P03 verifies their definitions are unchanged and adds no third index. Removing inherited duplicate index overhead requires a separate reviewed migration.

A version hashes the complete input-file checksum, selected layer key, declared scope/coverage/count/identity-field metadata, and importer format `environmental-v1`. Batch size and run timestamps are excluded. New output is streamed to one temporary file per overlay; no layer deepcopy or whole-layer serialized string is created. These temporary files are not durable raw-object storage. O01 must attach durable raw-reference associations separately without changing version identity solely because a new run observed the same bytes/scope.

The importer hashes and inspects metadata in one streaming pass, imports in a second pass, and verifies the full checksum again before validation. It uses bounded batches (32 features by default, at most 256; an 8MiB prepared-geometry threshold) and commits features with their checkpoint. A namespaced per-layer/version PostgreSQL session lock uses a dedicated NullPool connection, bounded connect/statement/lock timeouts, immediate `import_busy`, rollback before unlock, and physical close on every path. Only small catalog updates use C02's canonical lock.

Features retain original accepted EPSG:4326 float64 coordinates, holes and multipart shapes. There is no rounding, simplification, geometry repair, ordinal identity fallback, or silent deduplication. Explicit top-level IDs are the default; `--id-field FIELD` selects an authoritative source property. Missing/blank IDs, duplicate or conflicting IDs, declared geometry-family mismatches, invalid topology and oversize features are quarantined. Public attributes use an explicit flood/wetland allowlist; arbitrary source properties are discarded from this read model. Rejected reason counts and at most 25 identity/code samples are durable. SQL/parser exceptions are not emitted as raw source-bearing CLI messages.

Import states are loading, validated or failed. Any rejected feature, failed source coverage, or mismatch with a declared expected count prevents validation. Successful traversal with unknown source coverage remains coverage unknown. Equality of transport counts never establishes complete coverage. Partial/unknown source coverage is separate from artifact validation; P04 still requires its full activation checks. Catalog imports contain only the latest/pending item per layer, with a 50-entry and 50KiB bound. Existing ready layer entries are preserved, and old catalogs omit the imports property entirely so their body/revision remains compatible.

## Offline use

Use an explicit disposable copy and an isolated live PostgreSQL database upgraded through 0006. No command below fetches sources or activates the imported data. Default mode is a dry run: full traversal and spatial/identity checks use a temporary database table, with no persistent import or catalog writes.

```sh
python -m app.ingestion.cli import-environmental \
  --input /disposable-copy/environmental_overlays.json \
  --layer-id huntsville_fema_1pct_floodplain \
  --scope-id copied-legacy-unknown --batch-size 16 \
  --report /disposable-copy/dry-run-report.json
```

Review checksum, provenance, counts, geometry bounds and rejection reasons, then repeat with `--apply` to write shadow versions. Specify `--scope-version`, `--scope-file` and `--expected-count` only when they represent known source provenance. A nonzero exit indicates a failed import. There is no `complete` coverage option. Do not invent a new scope to bypass quarantined content.

Identical validated input replays without duplicate rows. Interrupted imports resume committed checkpoints from identical checksum/scope content. Input mutation or invalid JSON between passes is terminal quarantine for that version, including after restoring the original file: committed mixed chunks cannot later be treated as validated. Investigate the preserved diagnostics and raw evidence; P03 intentionally offers no destructive repair or automatic activation. Retain additive schema, imported versions and raw originals on application rollback. The migration refuses a downgrade that would destroy this provenance.

## Measurements and verification

Copied-snapshot acceptance passed on clean commit `bfff8aab2ff9aa4ba0396ab7c73a42314cd9b570` with:

```sh
node scripts/run-integration.mjs --suite api --scenario layer-import --snapshot-dir tmp/p03-snapshot
```

Run `2026-09-22T14-22-45-593Z-50ff1a99`; isolated project `urbanization_t01_69921bf58350`; cleanup result `removed`. Artifact manifest records clean working tree, exact image identities/versions and fixture checksums. Source and copy were 365,813,217 bytes with SHA256 `b55befdbd7ce73a08112bde63f3d22c515f069ef16e3a3aff142b119965c9762`; original was hashed before copying and after the import, unchanged. The source was only read, and the copy was mounted read-only.

| Copied layer | Seen | Accepted | Rejected | Import status | Coverage |
| --- | ---: | ---: | ---: | --- | --- |
| Huntsville FEMA 1% floodplain | 1,883 | 1,878 | 5 | failed | partial |
| Huntsville USFWS wetlands | 2,000 | 2,000 | 0 | validated | unknown |

Dry-run and apply counts matched. FEMA rejected three invalid topologies and two invalid rings; the importer did not repair or activate them. For each layer, 25 evenly spaced accepted source ordinals were streamed and compared against PostGIS `ST_AsGeoJSON(...,17)` using exact parsed coordinate equality. Synthetic tests separately cover holes and MultiPolygons. This sampling does not claim every copied coordinate was compared.

Measured importer process-lifetime high-water RSS was 105,078,784 bytes (about 100.21MiB), including synthetic checks and both copied dry-run/import sequences. It is not a per-import delta or a memory-budget guarantee. Total environmental table/index/TOAST storage after both imports was 55,779,328 bytes, including legacy/synthetic fixture rows and versions. The parser imposes feature event/string/estimated-byte limits, but the streaming library can allocate one oversized scalar before the application rejects it; arbitrary hostile-token memory is not strictly bounded by these checks.

This measurement predates the later durable-diagnostics/first-layer-display fixes; final synthetic/browser gates below verify those runtime changes. An earlier real scenario failed because its test incorrectly assumed exactly one inherited GiST index. The corrected test compares pre/post migration index definitions; no production schema workaround was made.

The subsequent clean real-browser run `2026-09-22T14-35-14-474Z-961e170c` passed on `2b4b96b6bd7c6f80fd5fb5e4c7b25c8f1eaf3dbb`; isolated project `urbanization_t01_1985fdb39454` was removed. It added actual child-process termination after a committed checkpoint and successful resume, physical lock release on database-connection death, durable rejection reason reloads, successful-resume failure clearing, new-output bridge checks, and accurate first-layer versus retained-ready failure UI. Playwright executed three passing tests; C01/U00 scenario-specific tests were intentionally skipped. Its screenshot was inspected, then progress text received a small padding adjustment for consistency with the layer panel.

The full installed API suite passed 134 tests with two upstream TestClient deprecation warnings; Ruff and mypy passed (37 modules). A clean Docker `npm ci` production build passed. An initial host build used an inherited MapLibre 4.7.1 installation rather than the locked 6.x dependency; no shared dependency changes were made. The clean Docker build resolved that environment issue. An earlier API-only test mount omitted root `render.yaml`; its two layout-dependent tests passed when rerun with the whole checkout mounted.

Final integrated gate results and PR review: pending C03/S02 dependency integration, final pipeline bridge/catalog regression, and CI. Historical clean results above are not claims about an untested final integration head.
