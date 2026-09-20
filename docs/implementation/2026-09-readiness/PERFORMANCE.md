# Map performance implementation plan

Prepared September 19, 2026. **Plan and proposed budgets; no optimization has been implemented by this planning task.** Start with the [dispatch instructions](DISPATCH.md) and use one PR guide at a time. The architecture below is fixed for the first pilot so a routine coding agent can execute without choosing a new stack.

## Problem and target

The review found a 365,813,217-byte saved environmental artifact and measured a 128,934,218-byte HTTP response taking 39.22 seconds. Both full overlays are fetched during map startup even when hidden. This was one local run with competing work, not a controlled latency benchmark. It establishes the payload problem, not a reliable p95.

The web build's MapLibre chunk was approximately 814 KB before compression / 222 KB gzip. Existing smoke tests mock a tiny API response. The main bottleneck is geometry delivery and repeated client/server processing; bundle tuning comes after eliminating the bulk transfer.

The useful result is a selectable development map/list with correctly labelled visible environmental context. It must preserve provenance, original screening geometry and honest coverage/error states.

## Fixed architecture

1. **Small metadata first.** The browser loads a <=50 KiB layer catalog and a bounded development viewport response. No page or toggle fetches the legacy whole environmental collection.
2. **Original environmental data in PostGIS.** Import immutable source versions, preserve accepted EPSG:4326 originals, add spatial indexes and retain raw artifact checksums.
3. **Display preprocessing once.** Generate projected, simplified, subdivided geometry by zoom band outside requests. Validate it, then atomically activate a complete version.
4. **Versioned vector tiles.** FastAPI queries indexed display parts for the requested viewport tile and returns MVT. Immutable version URLs support browser/proxy caching. Reuse existing infrastructure; no new tile server or queue broker.
5. **Bounded development summaries.** A transactional derived spatial index serves a viewport query with summary properties, deterministic pagination and a byte budget. Full record details load only on selection.
6. **Stable client effects.** Separate data changes from visibility, camera and selection. Abort obsolete requests; keep stable public IDs, bounded list DOM and explicit truncation.
7. **Measure the whole user action.** A blank fast map does not pass. Check rendered/selectable records, enabled overlays, list readiness and coverage labels.

Vector tiles suit the large static context geometry. The comparatively small development dataset can initially use bounded GeoJSON; introducing development MVT now would add selection/pagination complexity without measured need. If later scale breaches budgets, create a new measured proposal.

MapLibre's official [large-data guide](https://maplibre.org/maplibre-gl-js/docs/guides/large-data/) supports reducing client geometry/payload work. PostGIS provides the required [MVT output](https://postgis.net/docs/ST_AsMVT.html), [geometry clipping](https://postgis.net/docs/ST_AsMVTGeom.html) and [subdivision](https://postgis.net/docs/ST_Subdivide.html).

## Implementation order and handoff boundaries

| PR | Deliverable | What the agent must not combine |
| --- | --- | --- |
| [P01 — Establish a reproducible map performance baseline](P01-performance-baseline.md) | Generated fixture, controlled baseline, measurement command | No optimization |
| [P02 — Serve a small layer catalog and stop eager bulk overlay downloads](P02-layer-catalog-startup-relief.md) | Persisted catalog; remove eager bulk request | No temporary automatic bulk fallback |
| [P03 — Import versioned environmental geometry into indexed PostGIS storage](P03-canonical-environmental-storage.md) | Original versioned spatial import/indexes | No analysis simplification |
| [P04 — Prepare display geometry and activate complete layer versions atomically](P04-environmental-display-derivatives.md) | Display derivatives and atomic activation | No HTTP tile service |
| [P05 — Serve bounded, cached environmental vector tiles](P05-versioned-vector-tile-api.md) | Validated MVT endpoint, caching, limits | No map redesign |
| [P06 — Render catalog-driven vector overlays without bulk GeoJSON](P06-vector-overlay-client.md) | Catalog-driven vector overlays | No development endpoint migration |
| [P07 — Add an indexed viewport query for development summaries](P07-bounded-development-map-api.md) | Indexed bounded development summaries | No canonical storage rewrite |
| [P08 — Query developments by viewport and avoid redundant map work](P08-viewport-map-client.md) | Viewport client, cancellation, stable selection | No global state framework |
| [P09 — Enforce map payload and performance budgets in CI](P09-performance-regression-gates.md) | Regression budgets and reference reports | No threshold weakening to hide failures |

P02 offers early startup relief. Environmental controls will honestly say that tiles are being prepared until P06 lands; this intermediate state is for internal preview and does not satisfy the usable-map gate. U00 fixes current filter omissions early, independently of the later map architecture.

P03–P05 require lead review of geometry, migrations and caching. P02, P06, P08 and P09 are good bounded assignments for a cheaper coding agent once contracts/dependencies exist. P07 depends on the durable publication path so the map index cannot silently drift from detail records.

## Initial display settings

These are starting values to test, not measured optimal values or survey precision. The table uses EPSG:3857 coordinate units for display; those units are not a promise of ground-distance accuracy.

| Zoom band | Simplification tolerance | Render behavior |
| --- | --- | --- |
| Below 8 | None delivered | Show a zoom-in explanation |
| 8–10 | 100 projected metres | Broad context fills |
| 11–12 | 40 projected metres | City-scale context |
| 13–14 | 10 projected metres | Neighborhood context |
| 15–16 | 2 projected metres | Close visual inspection |
| 17–18 | 0 (original transformed geometry) | Highest supported display detail |

Apply ST_SimplifyPreserveTopology to a complete original feature, then ST_Subdivide with initial max_vertices=256. Store projected parts with GiST indexes. Do not simplify separately per tile or simplify canonical data. Small features can disappear at coarse display scales: disclose generalized display and check known narrow/important geometries before accepting tolerances.

Topology preservation applies within a feature, not automatically across adjacent features; [PostGIS documents that limitation](https://postgis.net/docs/ST_SimplifyPreserveTopology.html). Inspect holes and shared boundaries. Initially draw polygon fills without per-part outlines to avoid subdivision seams.

Use MVT extent 4096, buffer 64 and a corresponding expanded query envelope. Feature IDs and the fixed source-layer name must agree with the client. Analyze EXPLAIN (ANALYZE, BUFFERS) on representative selective queries; do not force an index for a tiny table where a sequential scan is legitimately cheaper.

If dense tiles exceed budgets, adjust offline derivative settings or zoom availability with visual review. Never drop arbitrary features, return an oversized tile as acceptable, or substitute a blank successful tile for an error.

## Proposed acceptance budgets

All values below are targets to verify in P01/P09, **not achieved measurements**.

| Measurement | Initial target / rule |
| --- | --- |
| Layer catalog | <=50 KiB decoded; no features/coordinates |
| Environmental tile | p95 <=250 KiB encoded; every tile <=1 MiB decoded |
| Development page | <=512 KiB decoded; default 500, max 1,000 records |
| Client accumulation | <=2,000 visible records; then disclose truncation |
| Result-list DOM | 50-row pages; <=100 mounted rows |
| First viewport app-data transfer | <=2 MiB encoded, including all enabled context tiles |
| Total first viewport transfer | Report separately; proposed <=5 MiB including JS/fonts/basemap |
| Desktop first useful development map | p95 <=3 seconds; enabled context ready <=5 seconds |
| Constrained mobile first useful map | p95 <=5 seconds; enabled context ready <=8 seconds |
| Catalog/detail API | warm p95 <=250 ms |
| Development viewport API | warm p95 <=400 ms |
| Tile API | warm p95 <=250 ms, cold p95 <=1 second |
| API query timeout | Initial 2 seconds for map reads; visible 503/error on expiry |
| Map-read API memory | Proposed <=512 MiB steady state on reference fixture |
| Optional in-process tile cache | Total <=64 MiB, bounded eviction |
| Map-route JS gzip | Report all route chunks; proposed <=400 KiB total |
| Hidden environmental layers | No new geometry downloads after hidden-state settles |
| No-data visual shortcut | Prohibited; readiness requires actual selectable/rendered fixtures |

Measure actual encoded transfer using network tooling; Content-Length alone is insufficient across compression and caches. Return Vary: Accept-Encoding, and ensure ETags refer to the served representation. Versioned tiles may use a one-year immutable cache; retain active/previous versions with a minimum seven-day replacement grace period and adjust retention to actual catalog/client lifetime. Catalogs revalidate after a short TTL, initially 60 seconds. Error responses use no-store.

## Benchmark protocol the agent must implement

**Fixture A, functional:** tens of developments plus environmental polygons with holes, multipolygons, touching boundaries, invalid/quarantined cases, one unlocated submission, complete/partial sources and dense tile edges.

**Fixture B, representative performance:** 1,324 development records and approximately 4,000 environmental features containing roughly four million coordinate pairs. Generator settings should yield a legacy serialized payload on the order of 100–150 MB; record actual bytes/checksums, not a claimed exact size. Include real geometric complexity rather than padding irrelevant strings. Generate outside measured time; commit code/seed/manifests, not the giant output.

**Fixture C, scale probe:** optional 100,000 development records to examine index/query behavior. This is diagnostic, not a new product scale promise.

**Copied June snapshot:** optional local corroboration using an isolated copy. Record checksum/counts. Never mutate the original data or commit third-party/private payloads.

Reference profile: PostgreSQL 16/PostGIS 3.4 with 2 CPUs/2 GiB, API with 1 CPU/1 GiB; record host CPU, OS, storage and browser version. Browser desktop viewport 1440x900; mobile 390x844, Chromium CPU throttling 4x, 10 Mbps down/1 Mbps up and 100 ms network latency. These are declared test profiles, not the user's actual hardware. Separate database cold-cache and browser cold-cache results; do not call a warm database run fully cold.

Run 10 fresh-context initial loads and report median/p95 plus all raw samples (small-sample p95 is approximate). Run 100 API requests per representative endpoint/scenario at concurrency 1 and 5; distinguish cache hit/miss. For interactions, repeat 20 pan/zoom/toggle/select/filter cycles and inspect long tasks, request churn and memory trend.

Use a deterministic local basemap/style fixture for required CI so a public provider outage cannot control correctness results. Also run an opt-in observation with the selected real basemap for O03; report its costs and failures separately. Controlled fixtures must still exercise vector rendering, glyph/sprite behavior where applicable, real application APIs and visible selection. Existing mocked smoke tests are not this benchmark.

## Evidence and regression policy

Save an artifact with commit SHA, dependency/image versions, fixture hash, profile, endpoint, bytes encoded/decoded, request count, timing distribution, cache state, SQL plans and process memory. Include Playwright trace/screenshots for user-visible correctness and a before/after table for each optimization.

Required PR checks should enforce deterministic size/count/no-bulk-request/functional assertions. Timing runs use a known reference profile; shared-runner noise gets investigated rather than hidden by arbitrary retries or moving thresholds. Report unmeasured budgets as unmeasured. An optimization is complete only if the changed path meets its functional and performance acceptance criteria.

Do not optimize gzip alone while retaining a giant decoded JSON parse, read the artifact on every catalog request, add limitless caches, call setData on visibility changes, put all rows in the DOM, or reuse simplified display geometry for environmental conclusions.

## Copyable assignment

> Implement one named P-series guide from this directory after its listed dependencies merge. Treat CONTRACTS.md and this performance plan as the design. Begin with the existing benchmark, make the smallest scoped change, and rerun the relevant real API/browser scenario. Return the diff, exact test commands, before/after measurements, source/geometry correctness evidence and rollback notes. If a contract proves impractical, document the measured reason for lead review instead of silently replacing the architecture. Keep deployment, live email and the working dataset unchanged.
