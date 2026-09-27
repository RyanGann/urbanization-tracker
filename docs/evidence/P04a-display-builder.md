# P04a shadow display builder — real PostGIS evidence

The classifier follow-up propagates every SQLSTATE class-40
transaction rollback condition, including `40000`, `40002` and `40003`, rather
than only serialization/deadlock codes. Focused regressions and the full API
suite passed (334 tests), along with Ruff and mypy. This changes no recipe,
geometry or successful output. The final source-fence proof includes this
classifier expansion. The owning CI scenario verifies the final PR head.

## Final source-fence proof

Clean code head `2c67dc3f99bfe2e182fd6be54826719dd06561f2` passed run
`2026-09-27T07-59-05-505Z-042fd0fd` with `working_tree_dirty=false`.
Before committing validation, the v5 builder locks/refetches the layer parent,
streams ID-only share locks over every existing feature row (including
unmanaged rows), rechecks the managed source snapshot/backend identity and
revalidates every completed band. The transaction retains these locks through
status commit; validated replay uses the same fence. Local lock and statement
timeouts are five and sixty seconds respectively.

A separate session changed unprocessed geometry after the first checkpoint
while bypassing the advisory-lock convention: finalization refused the old
identity and left the build nonvalidated. Separate-session geometry edits and
unmanaged-to-managed flag changes both received actual SQLSTATE `55P03` while
the final fence held. Earlier topology tamper, timeout/system-error rollback,
stable insertion-order identity and geometry checks passed again.
Final result SHA-256 is
`ec60c1594871fe1043ae8c716fe5c668227c95585c72eedbddf3c6da85fa29ed`;
display version is
`0d87115e2e17b49b4fd016f42c3d5c06104c96f2be46fb25c1467966242b6770`;
configuration SHA-256 is
`21634ca559f1be23b139022027b516b5911df1e96437f504661c21bc349eecaa`.
Original, source-based geometry part-set and SVG bytes remain unchanged, so
the earlier accepted visual QA scope still applies. Exact project
`urbanization_t01_6807f2ca5cdd` was removed; independent checks found zero
containers and volumes. Artifacts remain under
`tmp/agents/p04a/tmp/integration/2026-09-27T07-59-05-505Z-042fd0fd/`.

After this local proof, unmerged migration 0008 and the model add a nonpartial
`(environmental_layer_id, id)` B-tree to support ordered fencing of all parent
rows without relying on the managed-only identity index. The lock/hash/output
semantics are unchanged; final-head CI owns migration plus scenario validation.
No local full scenario was repeated solely for this index, and no production
plan or latency budget is claimed. The prior clean `741f0b4` run is retained
as pre-fix evidence only; it did not test the unmanaged-to-managed protection.

## Earlier authenticated-topology proof

Clean code head `06a0eb2c47910159390193b86ed444932fe42b9d` passed run
`2026-09-27T07-39-50-585Z-d4de6233` with `working_tree_dirty=false`.
The v4 recipe authenticates each result's source/display hole and component
counts, status, collapse flag and error code in its output digest, including
failed outcomes. Failed topology fields remain zero placeholders rather than
measured topology evidence. Successful replay independently recomputes source
counts and counts from a union of the saved display parts. Before union work,
replay verifies each part and caps each feature at 8,192 parts and 64 MiB.
All four metadata-only count edits were refused; restoring each field permitted
replay. This extends the earlier geometry, source lineage and checkpoint checks.

Final display version is
`de6a61f7c2f058d1146a6da77cb9d5c7a443016f09d2800ac329d938a1edc1d9`;
configuration SHA-256 is
`574da6e8c44af4c91897999fbcf364fdb16679377ed277215aa580a083dd94a7`.
Result SHA-256 is
`47f7aa440e244489fb5ddc558160ad696c9cfbb6211c46001c469f18b64123ec`.
The exact backend version is unchanged from the proof below. Actual statement
timeout, SQLSTATE 58030 rollback, unprocessed geometry mutation and reversed
insertion-order identity tests all passed again. The source-based geometry part
set, original EWKB and SVG bytes remain unchanged; accepted synthetic visual
QA still applies. This fixture provides correctness evidence, not a P09 replay
performance budget measurement. Ruff, mypy and all 331 API tests passed.
Exact project `urbanization_t01_059b15b22d7a` was removed; independent label
queries found zero containers and volumes. Artifacts remain under
`tmp/agents/p04a/tmp/integration/2026-09-27T07-39-50-585Z-d4de6233/`.

## Earlier geometry/runtime review-fix proof

Clean code head `b6a2a08dff731c73f9b1a0a6ca17ac04875189d7` passed run
`2026-09-27T07-29-17-065Z-370e8377` with `working_tree_dirty=false`.
The streaming source snapshot now includes an actual server-side SHA-256 of
each bounded canonical EWKB, returning digest metadata only and refusing
oversized snapshot inputs. A geometry-only edit to an unprocessed row with
unchanged importer fingerprint created a different display identity without
changing the prior committed checkpoint. Restoring the input resumed the
original version. Real PostgreSQL SQLSTATE `58030` and statement timeout
`57014` both rolled back a partially written batch; explicit resume succeeded.

The recipe now requires the actual PostGIS execution version (including GEOS
and PROJ), so backend changes produce distinct configuration/display hashes.
This run reported:

```text
POSTGIS="3.4.3 e365945" [EXTENSION] PGSQL="160" GEOS="3.9.0-CAPI-1.16.2" PROJ="7.2.1 NETWORK_ENABLED=OFF URL_ENDPOINT=https://cdn.proj.org USER_WRITABLE_DIRECTORY=/var/lib/postgresql/.local/share/proj DATABASE_PATH=/usr/share/proj/proj.db" LIBXML="2.9.10" LIBJSON="0.15" LIBPROTOBUF="1.3.3" WAGYU="0.5.0 (Internal)" TOPOLOGY
```

Display version is
`384c7863920195b446235bc5b20e25f796d46f8cda4b2389a89a7b7aa1136ef3`;
configuration SHA-256 is
`fd4921d0de9386f2fe81ceccaf8a525206790ae2f17095aea26155b61ae8ce54`.
Source-based part-set, original EWKB and SVG hashes match the earlier proofs
below, preserving the accepted synthetic visual QA scope. Final result SHA-256
is `bd4f0874f893bd156577954ac7ddcadbb61981beaa4bae3f340e6157a4f157ac`.
All 325 API tests, Ruff and mypy passed. Migration 0008 depends on O01 0007.
The owning CI workflow now runs `display-builder` after environmental import
and recovery, with the same runner isolation, artifact capture and teardown.
Exact project `urbanization_t01_5c253e52e733` was removed; independent label
queries found zero containers and volumes. Local artifacts remain under
`tmp/agents/p04a/tmp/integration/2026-09-27T07-29-17-065Z-370e8377/`.

## Earlier transient-failure proof

The final runtime change passed the same real scenario on clean code head
`e38d0b5e774524f55e203d02f8e2d086970549a3`, run
`2026-09-27T07-12-26-125Z-33254933`. After a durable two-feature checkpoint,
the scenario injected a real PostgreSQL statement timeout in the next batch.
The exception rolled back the entire uncommitted batch: checkpoint fields,
result count and part digest stayed unchanged. An explicit subsequent resume
completed the same display version. Permanent geometry failures still produce
accounted diagnostics; transient database errors do not poison immutable results.

`statement_timeout_preserves_committed_checkpoint` is true. The display version,
configuration, original geometry, source-based part-set and SVG hashes match
the earlier clean proof below, so its accepted visual QA remains applicable.
The selective default plan again used the projected GiST bitmap index, returned
one row and touched seven shared-hit blocks (single execution 0.077 ms).
Final `results.json` SHA-256 is
`5f8a4ced63b33108e48e3f904fb471f15bf1e06133d8ef76323a6c060309c5bc`.
The run removed exact project `urbanization_t01_f6a29bde067c`; independent
label checks found zero containers and zero volumes. Ruff, mypy (56 application
files), and all 323 API tests passed in the pinned no-network check image.

Only the P04a commits were subsequently rebased onto merged O01 main
`8b095973e21cc9237621d84681310eb1997ea208`, producing
`79cf194f754e65e16a49a38829736973f04ce521`. A complete Git tree diff against
the real-tested code head is empty; the parent replacement changed no files.
Machine-readable artifacts remain under
`tmp/agents/p04a/tmp/integration/2026-09-27T07-12-26-125Z-33254933/`.

## September 27 clean committed-head proof

The isolated builder was rebased onto exact O01 head
`72e1ccd42f5dad43d323a8567c136b9e9f866486`. On clean P04a code head
`ff9147ff16ceb11ec8069b136bbca84bd9eb9e3a`, this command passed:

```text
node scripts/run-integration.mjs --suite api --scenario display-builder
run_id: 2026-09-27T07-02-21-214Z-be1c3937
working_tree_dirty: false
outcome: passed
cleanup_result: removed
results.json SHA-256: a9fd67615604221fd646adc318c2c762d648205c72cf679db263c44e862df89f
```

All five required bands processed all five synthetic polygon-family features.
The process was killed after its first committed two-feature checkpoint,
resumed with a different batch size, and replayed without duplicate parts.
Recreating the same layer content with reversed insertion order produced the
same display version, stable band checksums and source-based part-set checksum,
despite different database feature IDs. Internal `checkpoint_sha256` binds
numeric traversal separately from completed `parts_sha256`, which binds source
identities and output digests in C collation order. The recipe includes the
input/output rejection limits as well as projection, tolerances and topology
validation settings.

The P04 geometry fixture SHA-256 is
`40f3c8bae8f81416ea52a19965364fb3792bd8604efe1f29a715573d756a37ca`;
the general T01 seed fixture SHA-256 is
`932eacb03655a3dee1a2838abf9ddf8d5dfa44f744482408611b61a2561bbee2`.
The final source-based part-set SHA-256 is
`ddd817b079733fea98e6b8c48ad347fb59a375570f83390cb15720c318b69e78`.
Original EPSG:4326 EWKB remained
`ac3b7a0c5522893ca5cb578d5925fb86b6e17e06d8554ed1a30d877291b7d96f`
and exact screening remained one hit. The hole remained one hole, the
multipolygon remained two components, and the dense feature generated four
parts at z17–18 with at most 153 vertices per part (limit 256). Every band
rejected the out-of-domain latitude fixture without altering originals. Replay
refused both a coherent part geometry/digest edit and a changed part source ID.

Input batches now retain metadata only, with one bounded EWKB fetched per
feature; replay streams original geometry with `yield_per=1` and guards the
current byte size before transferring it. The configured limits are 32 MiB
input EWKB, one million input vertices, 8,192 parts and 64 MiB output per
feature. A deliberately enlarged canonical geometry was refused on replay
using a lowered 512-byte transfer guard, avoiding a resource-heavy 32 MiB test
allocation. This proves the guard mechanism, not a measured process RSS limit.

The default selective `EXPLAIN (ANALYZE, BUFFERS)` over 6,000 bounded synthetic
background parts used `ix_environmental_display_parts_geometry` in a bitmap
index scan, returned one row and touched seven shared-hit blocks. Its single
execution measured 0.134 ms; this is query-plan evidence, not a latency
benchmark or p95 claim. The artificial background build remained incomplete
and never became a validated derivative or publication input. The tiny core
fixture's default plan and a separately forced index diagnostic are retained
as separate observations.

The scenario retained `p04a/fill-only-bands.svg` and an offline Playwright
render retained `p04a/fill-only-bands.png`. Root visual QA accepted the fixed
scale synthetic generalization sample: holes, multipart pieces and the
adjacent edge remain visible, and the narrow channel remains a thin fill.
The dense z17–18 sample shows faint antialias hairlines between SVG paths;
PostGIS union equality passed, so no geometry gap was introduced. P06 must
check antialias behavior in the actual map renderer. These samples do not
establish real map/tile-client acceptance at the advertised zoom levels.
SVG SHA-256 is
`2f25f77c53b9a04c5e7fecf8be2ffb91b34163e9e9704d4e52baa4f431e13a93`;
PNG SHA-256 is
`35972d37dbe452ba4eedfa51c47eb599198ef052d24b39583e3e8ae7840a7fc4`.

Ruff passed for `app tests alembic`, mypy passed for 56 application files, and
the full API suite passed 309 tests with two upstream deprecation warnings in
the existing no-network check image. Its 57 dependency pins match the committed
lock file. The real run migrated through additive 0008, removed its exact
Docker project `urbanization_t01_a5f293d47053`, and an independent project-label
check found zero remaining containers and volumes. Machine-readable artifacts
are under `tmp/agents/p04a/tmp/integration/2026-09-27T07-02-21-214Z-be1c3937/`.
No active pointer, public tile URL, source refresh or canonical mutation was
introduced. Public activation and provenance/source-use gates remain P04b and
bridge work.

## Earlier September 24 checkpoint proof

Run on 2026-09-24 from the isolated `codex/p04a-display-builder` worktree:

```text
node scripts/run-integration.mjs --suite api --scenario display-builder
run_id: 2026-09-24T07-28-21-674Z-abcd3264
outcome: passed
cleanup_result: removed
result_sha256: 81519749f93f515d1836b95726fdc98f2c54a970672cb7db5e9a239778ef17a6
```

The disposable stack migrated through 0008 and built all five display bands
from five synthetic polygon-family features. It actually killed the builder
after the first committed two-feature checkpoint, resumed with a different
batch size, and replayed the validated result. It checked that original
EPSG:4326 EWKB SHA-256 and exact spatial screening count did not change. A
hole stayed one hole and a multipolygon stayed two components. The dense
polygon produced four parts at z17–18; all emitted parts had at most 153
vertices (limit 256). The tiny fixture's default viewport plan was recorded;
a separately forced diagnostic proved the projected GiST index is usable,
without claiming the default planner selected it. The part-set SHA-256 after replay was
`23af6abfd2951fe0779420cb2ffe7c41cd2de03d5dd4f75231ea1d065d2265cc`.

The same run translated a stored part and updated its row digest; replay
refused the changed per-feature output digest. A deliberately failing PostGIS
statement inside one feature savepoint left the outer batch usable for the
next feature. A polygon outside the supported Web Mercator latitude failed
closed in every band. A failed/partial P03 import produced a validated *display*
diagnostic with `publicly_active=false`; after synthetic same-version P03
resume, the source snapshot hash yielded a new immutable display version while
the prior shadow build stayed intact. No public catalog or active pointer
changed. The run removed its Docker project.

The locked `c04-api-check:local` image subsequently passed `ruff check app
tests alembic`, `mypy app` (55 source files), and 31 affected unit tests
(`test_display_config.py`, `test_environmental_import.py`,
`test_environmental_output.py`, `test_ingestion_cli.py`). A follow-up changed
the source snapshot hash to stable source identities instead of database IDs;
the full real-stack scenario will be rerun after rebasing onto merged O01.

Machine-readable local artifacts are under
`tmp/agents/p04a/tmp/integration/2026-09-24T07-28-21-674Z-abcd3264/`
(`manifest.json`, `p04a/results.json`, `cleanup-result.json`). This test uses
synthetic geometry and does not establish production FEMA or wetlands coverage,
source rights, or public activation; P04b must check those independent gates.

The builder only inserts parts/results for a version and verifies them on
replay. Unique keys, restricted parent deletes, and the refusal to downgrade
protect version/checkpoint evidence, but the database does not prohibit a
privileged writer from updating an existing part. P04b retention will need
controlled deletion; any public activation must reverify the derivative and
source provenance rather than treating the P04a status as a DB write lock.
