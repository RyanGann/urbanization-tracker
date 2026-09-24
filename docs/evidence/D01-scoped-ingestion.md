# D01 scoped ingestion — local implementation evidence

This branch adds a **staging and coverage-attempt path**. It does not activate a
new source snapshot or claim that the current public dataset covers the city.
The existing `ingest-huntsville` and `ingest-madison-county` commands remain
legacy capped runs and their coverage remains unknown/partial under C03.

## Declared scope and missing reviewed artifact

The pilot is the **City of Huntsville corporate-limits polygon**, not its
bounding box or all of Madison County. The identified source is
`Boundaries/CityLimits/MapServer/0`, selected by `CityName = 'Huntsville'`.
Development queries intersect the city polygon. Environmental screening queries
intersect a separately reviewed **510 m guarded context** polygon, buffered in
EPSG:5070 and transformed to EPSG:4326. The 10 m guard covers the intended
500 m screening radius despite polygon-buffer approximation. The default building-permit predicate has **no
time cutoff**: all available permits intersecting the city are in scope.

The repository does not yet contain a reviewed polygon artifact. The staging
command therefore requires an operator-supplied JSON scope file and refuses to
run without it. Its exact schema is:

```json
{
  "version": "huntsville-city-limits-layer0-repaired-guard10-v1",
  "boundary_source_url": "https://maps.huntsvilleal.gov/server/rest/services/Boundaries/CityLimits/MapServer/0",
  "boundary_where": "CityName = 'Huntsville'",
  "source_srid": 102629,
  "raw_boundary_response_sha256": "sha256 of the captured ArcGIS WGS84 response bytes",
  "boundary_algorithm": "ArcGIS-rings-ST_MakeValid-linework-v1",
  "boundary_geometry": {"rings": [], "spatialReference": {"wkid": 4326}},
  "boundary_sha256": "sha256 of canonical boundary_geometry JSON",
  "context_geometry": {"rings": [], "spatialReference": {"wkid": 4326}},
  "context_sha256": "sha256 of canonical context_geometry JSON",
  "context_buffer_m": 510,
  "context_algorithm": "EPSG:5070-buffer-510m-for-500m-screening-v1",
  "reviewed_at": "human-reviewed UTC timestamp"
}
```

`rings` above are placeholders, **not** a runnable boundary. Capture the
current layer-0 polygon in an isolated, bounded query. Independently verify
its city-name selector, source/effective dates, geometry validity, and
EPSG:4326 conversion. The live ring set has a self-intersection, so the pilot
candidate explicitly assembles ArcGIS exterior/hole rings and applies PostGIS
`ST_MakeValid` before use. Produce the context polygon by buffering that
repaired boundary 510 m in EPSG:5070, then transform it back to 4326. Verify
that it contains both the city polygon and an independently calculated 500 m
screening buffer. Record the source response
and both geometry digests before setting `reviewed_at`. A checksum and timestamp
inside a file do not authenticate the source or review; that is a human release
step. A geometry/time/filter change requires a new scope version.

### Live boundary correction and candidate capture (2026-09-23 UTC)

The earlier documented layer 2 now returns `{"error":{"code":404,"message":"Layer not found"}}`
with HTTP 200. The parent service advertises only layer 0, `CityLimits`; its
polygon metadata still reports WKID 102629 and the `CityName` field. D01 now
requires `huntsville-city-limits-layer0-repaired-guard10-v1` and `/0`; the old scope version is
rejected. The exact `CityName = 'Huntsville'` count is one, and its sole returned
feature has `OBJECTID=62404`, `Eff_Date=2026-08-19T05:00:00Z`, and
`Mod_Date=2026-09-23T18:32:17Z`. ArcGIS returned 165 rings and 12,050 points
at `outSR=4326`; a native `outSR=102629` response returned the same ID/name
with 165 rings and 12,045 points. The transformed response declares WKID 4326.
These are **current bounded observations**, not proof that the polygon is the
correct publication boundary. The local derived artifact was subsequently
reviewed for bounded testing; rights and production activation remain pending.

The six read-only boundary/setup responses total 981,102 bytes, below the
16 MiB cap. Their exact URLs, byte counts and SHA-256 hashes are in the
ignored `tmp/d01-live/candidate-report.json` evidence bundle. Source response
JSON remains local because public bulk redistribution terms have not been cleared.

PostGIS 3.4.3/GEOS 3.9.0 assembled the 2 clockwise exterior rings and 163
counterclockwise holes, assigning every hole to a containing exterior. The
resulting raw two-component multipolygon has a ring self-intersection at
`[-86.5354204655259, 34.5496702199901]`. Its source-ring linework Hausdorff
distance is zero; the naive `ST_BuildArea` result had omitted the main city
polygon and was rejected. Explicit `ST_MakeValid` produces a valid two-component
multipolygon with 174 rings and 12,059 points. Its geodesic area is
604,385,661.89 m², unchanged from the raw assembled area's reported value;
raw/repaired boundary Hausdorff distance is zero. As a second repair
interpretation, `ST_Buffer(raw, 0)` is valid and has **zero** geodesic
symmetric-difference area against `ST_MakeValid`. The boundary WGS84 bounds are
`[-86.95669983, 34.50354936, -86.38550630, 34.86515553]`. These zero deltas
do not make the original ring topology valid; the repair is a declared,
review-gated derived artifact.

A nominal 500 m buffer had a 0.706 m² miss against a separately calculated
499 m buffer, due to polygonal arc approximation. The new 510 m EPSG:5070
context is valid and **fully covers** the separately calculated 500 m screening
buffer (`ST_Covers=true`, missing area 0 m²). The minimum repaired-boundary to
context-boundary distance is 501.824 m. Its geodesic area is 903,946,129.81 m²
and WGS84 bounds are
`[-86.96229896, 34.49899181, -86.37989456, 34.86970336]`. The exact
unreviewed candidate is in ignored
`tmp/d01-live/huntsville-city-limits-layer0-repaired-guard10-v1.candidate.json`;
`reviewed_at` is null. Local raw/repaired plots are
`tmp/d01-live/boundary-raw-review.png` and
`tmp/d01-live/boundary-repaired-context-review.png`.

### Bounded live source canary (2026-09-24 UTC)

After lead inspection of the derived boundary, a local ignored copy received
`reviewed_at=2026-09-24T04:43:51.111Z`. A separate direct-HTTPS diagnostic
used that exact boundary/context for one metadata, one scoped count, one scoped
ID set and at most one 25-feature geometry request per existing source. It
paced requests at least 1.1 seconds apart globally, did not retry, made no
source-health or canonical writes, and stopped before geometry on inconsistent
count/ID responses. It was **not** the Python staging CLI; a live CLI test
remains to be done after the fixture and O01 integration gates.

| Source | Requests / response bytes | Scoped count / unique IDs | Geometry sample | Result |
| --- | ---: | ---: | --- | --- |
| New subdivisions | 4 / 87,139 B | 343 / 343 | 25 polygons | Pass |
| Building permits | 4 / 140,984 B | 17,902 / 17,902 | 25 points | Pass |
| FEMA 1% floodplain | 4 / 1,062,946 B | 1,210 / 1,210 | 25 Polygon/MultiPolygon features | Pass |
| USFWS wetlands | 3 / 23,706 B | 2,499 / 2,498 | Stopped before geometry | Count/ID mismatch |
| Madison County subdivisions | 3 / 39,306 B | 4,718 / 4,724 | Stopped before geometry | Count/ID mismatch |

All 18 first-pass requests returned HTTP 200. Each layer reported its expected
geometry type, WKID 102629, OBJECTID and required field names; no metadata
field/CRS drift or sampled missing geometry was observed. The three geometry
samples used read-only form POST and remained within the 25-feature cap.
The exact endpoint/method/status, request-body and response SHA-256, byte count
and ignored raw response are recorded in
`tmp/d01-live/canary-2026-09-24T04-46-31.315Z/report.json` (report SHA-256
`a94dce49135cd7a376cccb51a9c7c1b2d3836823d278d4a271974ee9f37ee1cc`).

A further **two requests per discrepant source** repeated only the same-scope
count and ID queries. Wetlands again returned 2,499 versus 2,498 IDs; county
again returned 4,718 versus 4,724 IDs. For each source, both request-body
digests and both response-byte digests matched the first run exactly. The ID
set hashes remained `1d0aaccda6234f9a050c385d07c4da8eb8601e1d7c375c22335a0788d3dca60e`
and `de104438157ff6bd35299b4608b689aa85c9d0b6c9f202b743a5200c1ff35df5`
respectively. The repeated discrepancy is therefore stable in these two
observations; its upstream cause is not established. D01 must not call either
source complete until a defensible source-specific reconciliation is tested.
The follow-up report is ignored at
`tmp/d01-live/count-id-followup-2026-09-24T04-48-11.176Z/report.json`
(SHA-256 `50c5566d4dfa5fcaf9b3d2f89bcca5f93c88ed50c6321680f6000be3375c8dde`).

All official source responses, full derived geometry and plots stay in ignored
local evidence. The City GIS Data Depot's copyright/repackaging terms require
the O04 rights decision before any official geometry is committed or publicly
redistributed.

## Commands and safety boundaries

```text
python -m app.ingestion.cli stage-scoped-arcgis \
  --scope-file /isolated/reviewed-scope.json \
  --output-dir /isolated/staging \
  --source huntsville_building_permits --canary

python -m app.ingestion.cli stage-scoped-arcgis \
  --scope-file /isolated/reviewed-scope.json \
  --output-dir /isolated/staging \
  --source huntsville_building_permits --record-attempt
```

The first command uses at most four read-only HTTP requests for a source:
metadata, same-scope count, IDs and at most 25 geometries. It never changes
source health or claims complete coverage. Canary requests have at least a
one-second interval, no retries, and a sanitized per-request method, endpoint,
operation, status, response byte count and query digest log; a 429 stops that
source. When multiple sources are selected, the CLI waits at least one second
between them. The second command stages bounded pages,
re-enumerates source IDs, writes a sanitized report and updates PostgreSQL
source-health **attempt** fields only. That health row preserves the previous
`last_success_at`, marks publication `not_activated`, and leaves all canonical
records untouched. Neither command runs during ordinary CI.

Each source defaults to at most 100,000 IDs, an 8 MiB ID response, 32 MiB
individual response, 1 GiB received bytes, 1,000 HTTP attempts and 10 minutes.
The connector batches 250 points or 32 polygons, retries transient 429/5xx and
transport failures at most three times with bounded delay, and stops with
partial/failed coverage on exhaustion. Count, ID enumeration, ID batches and
the final enumeration use identical spatial and time parameters. The full city
polygon exceeds safe URL length, so long read-only ArcGIS queries use
form-encoded POST while metadata and short queries use GET; both count against
the same request cap, following [Esri's long-JSON guidance](https://developers.arcgis.com/rest/services-reference/enterprise/get-started-with-the-services-directory/). A verified
empty count/ID set is complete empty; a canary, failed validation, changing
IDs or a safety stop cannot be complete. An explicit offset fallback requires
stable object-ID order, count and source edit-version reconciliation. It does
not stop on a full page just because `exceededTransferLimit` is absent.

## Activation gate

`source_batch_from_staging` is an **internal, non-publishing** C03 adapter. It carries
scope ID/version, boundary/context hashes, expected/fetched/accepted/rejected
counts and coverage into `SourceBatch`; C03 only marks previously observed
records `source_missing` for a complete batch. This adapter is intentionally
**not called by the staging CLI**. O01 must first checksum-verify and seal the
raw pages **and the report artifact**. A caller must then independently read
the sealed report/pages, recompute counts, object IDs and normalization results,
and invoke the adapter before entering C02's short canonical transaction.
The current adapter checks caller-supplied report/page digest assertions but has no
O01 sealed-reference lookup yet; those strings alone are not proof of
provenance. Until that lookup is integrated, no scoped source activation is
authorized. Environmental activation also needs P03/P04's immutable-version
and last-good pointer gate. Failed/partial environmental output must never
replace a ready version as complete.

## Validation status

The new deterministic HTTP fixture covers ID-batch pagination, count/ID
mismatch, duplicate/missing IDs, changed IDs, 429/retry, invalid geometry,
empty scope, canary budget, long-query form POST, safety cap, offset full-page flag omission and
repeated offset pages. The fixture also checks that staged health preserves
the previous last-good time and that a forged complete report is refused
without reconciliation evidence. The bounded boundary capture, isolated PostGIS
topology/buffer derivation, direct-HTTPS source canary, pinned Python Ruff/mypy
and focused fixture tests have run. The focused suite finished **16 passed**.
The real T01 `--suite api --scenario d01-scoped` run
`2026-09-24T04-54-18-604Z-fa5c54a8` passed on the then-dirty D01 branch:
synthetic local HTTP ArcGIS completed a five-request, two-feature page and
failed closed on a three-request count/ID mismatch. Real PostgreSQL source
health showed a failed, unactivated attempt while preserving the prior complete
coverage, September 1 last-success time and nine published records. The
development-record SHA-256 stayed
`1d172925e37ef2209624c3581af4d560dda6f8f8011058adfdfd8f3c0812a65e`
through an API restart. Scenario result SHA-256:
`9d1989ff41645487b3431f35cf2dc0fc8116210fff33727009db002de1692104`;
the isolated Compose project reports `cleanup_result: removed`. After rebasing
onto main `4923c4b` and fixing received-byte budget accounting, locked Ruff and
mypy passed, and the full backend suite passed **138 tests**. The isolated
pre-review-fix T01 run `2026-09-24T05-02-32-774Z-9d9b7075` passed: five complete
synthetic HTTP requests, three expected failed requests, source health degraded
without activation, and last-good development rows unchanged across API restart
(SHA-256 `e25584e9dc1d026560f8785f53b0742bc1677b710c86c5d8994d510ce8754d02`).
Its Compose project reports `cleanup_result: removed`. The live source probe
was a separate direct-HTTPS diagnostic; the Python staging CLI has **not** been
run against those official services, nor has any complete source replacement
been activated. No canonical source, saved snapshot, external bucket, or public
layer was changed.

Codex review identified that bounding-box validation alone accepted malformed
polygon rings. Commit `365dc17` adds ring structure and Shapely topology
checks, plus short/open/misnested/self-intersecting/outside-hole regression
cases. On that commit, locked Ruff/mypy passed and the full backend suite passed
**164 tests**. The isolated real API/PostGIS scenario
`2026-09-24T05-17-38-183Z-09b43516` passed with five complete and three
expected failed fixture requests. The failed attempt remained unactivated,
preserved the September 1 last-success time and nine published records, and
left development rows unchanged through restart (SHA-256
`249a59e482aef30452e2bbeb0e8d69af227698f1ff39af7706840fab378a6030`).
Its Compose project also reports `cleanup_result: removed`.

Further Codex review identified two more fail-closed cases and an aggregate
health gap. Reviewed WGS84 scope coordinates now require valid longitude and
latitude bounds; non-finite or overflowing JSON numbers fail as scoped reports,
and huge-integer geometry is rejected without aborting the collector. An
unactivated `staged` source also keeps overall health degraded when a later
legacy run updates other rows. On code head `56979c8`, locked full API Ruff and
mypy passed, as did **172 backend tests**. The isolated D01 real API/PostGIS run
`2026-09-24T05-32-56-133Z-ab5235f8` passed with five complete and three
expected failed fixture requests. The failed attempt remained unactivated,
preserved nine published records and the September 1 last-success time, and
left development rows unchanged across restart (SHA-256
`d020a6d6621d1af39189d20125c16c37f20efa1fa2d8a8498b009f079ba03b5e`).
Its disposable Compose project reports `cleanup_result: removed`.

The next review found that a page with a valid object ID and geometry but a
missing configured source property could be counted as accepted. Code head
`bac72c2` checks required per-feature property keys before acceptance, so such
a page is partial. Locked full API Ruff/mypy and **173 backend tests** passed.
The isolated D01 T01 run `2026-09-24T05-37-25-948Z-18e22b9f` passed with five
complete and three expected failed fixture requests; the failed attempt
remained unactivated and preserved last-good records through restart (identical
development SHA-256 before/after:
`357684e3880849e553322b0d1d0ba3913f39f9cac9d2a7489c47fd6899953540`).
Its disposable Compose project reports `cleanup_result: removed`.

The CLI now exits nonzero for any full staging run whose coverage is not
`complete`, including rejected-feature partial results with no transport error;
canaries remain unknown by design. Code head `ce67c68` passed locked full API
Ruff/mypy and **177 backend tests**, including CLI exit-status regressions. Its
isolated D01 T01 run `2026-09-24T05-53-29-694Z-104e267a` passed with five
complete and three expected failed fixture requests. The failed attempt was
unactivated, retained the September 1 success time and nine published records,
and left development records unchanged through restart (SHA-256
`6118c305216f99a0126eb01dbd00297ae2601a2cea0eb1a3ee2411e36833ee69`).
The disposable Compose project reports `cleanup_result: removed`.

A final scope-validation review found that a closed reviewed ring could still
be degenerate or self-intersecting. Code head `409ad09` requires at least three
distinct vertices per ring and a valid assembled nested ArcGIS polygon. The
ignored, lead-reviewed repaired city boundary and 510 m context both passed
this checker with their previously recorded SHA-256 digests
`2c4f6a2749c12f7b788c08f75f92c5c882bd5a0231e3881f1807ee7420f6d215`
and `83540d80a62fc62a438753903ff81b6bda92fe95671c5f6c619d7936aab357a8`.
Locked full API Ruff/mypy and **181 backend tests** passed. The isolated D01
T01 run `2026-09-24T06-05-36-043Z-76c74ee0` passed with five complete and
three expected failed fixture requests; the failed attempt stayed unactivated
and left last-good development records unchanged across restart (SHA-256
`943593a541af4b1ed3b7abb222d5d1333fec8edc571e1bbfa4a3f594be82f5ed`).
The disposable Compose project reports `cleanup_result: removed`.

After rebasing D01 onto merged P03 main
`96aaa5b9af9626063db88cfc7e5adacfd0ae7e6c`, the integration runner
preserves both P03 `layer-import` and D01 `d01-scoped` scenarios. Locked full
API Ruff/mypy and **211 backend tests** passed on the rebased code. The isolated
D01 T01 run `2026-09-24T06-19-17-669Z-b385e8f6` passed: five complete and
three expected failed synthetic requests, degraded unactivated health, the
September 1 success time and nine published records retained, and unchanged
development rows across restart (SHA-256
`73384a89a07948a3fa81bb390226c3b46452a93a812bd0b7d1688e5a04b786d6`).
The disposable Compose project reports `cleanup_result: removed`.
