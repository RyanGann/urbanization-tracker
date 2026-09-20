# Shared implementation contracts

Prepared September 19, 2026. **These contracts define implementation scope; current status and evidence are in [plan.json](plan.json).** The PR guides own their implementation. Changes to these contracts require lead review and updates to every affected guide, schema and test. Keep the React/MapLibre + FastAPI + PostgreSQL/PostGIS architecture. Do not add Redis/Celery, a second tile service or a God’s Eye View dependency to solve the current pilot.

## 1. Data modes, availability and errors — C01, U00

Add `DATA_MODE=live|demo`, default `live`. Store backend selection is separate. Hosted mode requires PostgreSQL; artifact mode is supported for local single-writer development. Demo mode is explicit, visibly labelled and forbidden by hosted preflight.

An initialized empty canonical collection is available and returns zero records. A missing/uninitialized store is unavailable, and decoding/database failures are errors. No live path may fall back to seeded developments or environmental context.

Add a small `GET /api/dataset-status` response with `data_mode`, `availability` (ready/uninitialized/unavailable), dataset revision, source freshness and declared scope. Catalog responses also carry data mode. Liveness stays `/health`; readiness and source health are separate.

New/changed endpoints use FastAPI's `detail` envelope with an object containing stable `code`, safe `message`, and optional field/retry information. Examples: `data_unavailable`, `dataset_changed`, `review_revision_conflict`, `review_not_actionable`. Never return secrets, SQL, private request bodies or full source payloads in errors.

| Condition | HTTP behavior |
| --- | --- |
| Available empty collection / known empty ready tile | 200 with a valid empty representation |
| Unknown record/layer/version | 404 |
| Deliberately expired immutable version | 410 |
| Stale review revision or paginated dataset revision | 409 |
| Invalid query/geometry/filter | 422; oversized body 413 |
| Shared write quota reached | 429 with Retry-After |
| Required database/index/artifact dependency unavailable | 503; no seed or healthy-empty substitute |

For statuses/types/confidence/flags, **absent parameters mean all**, repeated parameters form a selected subset, and `status=none` (equivalently for the other filter names) means no selected values. `none` cannot be combined with real values. Explicit empty selections return zero; unknown values fail validation. Retain existing parameter names: `status`, `development_type`, `confidence`, `flag`.

Known statuses: layout, preliminary, final, issued_permit, completed, proposed. Type options include subdivision, building_permit, public_submission and any deliberately supported canonical type. Both old list endpoints and new viewport endpoints must share one filter parser.

## 2. Stable identity, revisions and transactions — C02–C06

Source identity is `(source_key, source_record_id)`. Preserve existing public IDs through a registry and aliases; mutable title/status/geometry never forms a new identity. Missing or ambiguous source IDs are quarantined. Preserve `date_discovered` on refresh.

Candidate identity is distinct from candidate revision; logical agenda document identity is distinct from downloaded blob hash. Use authoritative immutable item IDs when available; otherwise persist an internal ID and observation mapping. Mutable title/phase/position cannot form a fallback ID. Changed observations without a stable item anchor require an explicit audited link to an existing candidate or creation of a new one. Unchanged content preserves decisions; resolved changed content creates a pending revision while retaining prior decisions and published versions. Publication requires S02-validated geometry with supported location provenance; staging permits an explicitly unknown location.

A public-content fingerprint uses canonical JSON ordering and a versioned field allowlist: title/description, normalized and source status, type, public provenance/source identifiers, public dates other than checked time, geometry/provenance/confidence, approved public attributes and contextual flags. Exclude fetch timestamps, last_checked, reviewer private notes/contact, raw payloads, transient health and ordering noise. Normalize semantically equivalent geometry/property ordering before fingerprinting without lowering canonical coordinate precision. Store the fingerprint algorithm version.

For pilot correctness, use one transaction-level PostgreSQL advisory lock for canonical/operational mutation: namespace `2088694651`, key `1`. Acquire it before reading state to modify, using a shared SQLAlchemy Session and bounded lock/statement timeouts. Nested helpers must not independently commit. This intentionally serializes short pilot writes; reassess only after measurement. Fetches, uploads, PDF parsing and SMTP stay outside the lock/transaction.

Convert writers incrementally: C02 creation paths; C03 source merges; C04 agenda merges; C05 review/import actions; C06 publication; C07 matcher; C08 sender; S03 subscription lifecycle; C09 merge. Until all affected writers migrate, do not claim concurrent production safety. Replace ordinary whole-collection delete/reinsert with item upserts/deletes. Maintenance import is explicit and locked.

Add `publication_events` using string public_id (not a guessed FK to unused integer model scaffolding), unique `(public_id, revision)`, event ID, kind, before/after public snapshots, source/run provenance, content hash/version, occurred_at, notify_eligible and matcher processing state. Kinds: published, changed, retracted, context_changed, merged; baseline is a non-notifying migration event. Canonical write and event commit together; once P07 enables the map index, its projection commits in that transaction too. Before enabling it, install the hook in every active writer, backfill/reconcile under the canonical mutation lock and atomically mark the index ready. A no-op refresh advances freshness only. Retain genuine history and disclose when tracking began.

Review mutations require `expected_revision`. Automatically published valid ArcGIS audit rows are read-only; manual candidates expose allowed_actions. Known but disallowed action is 409. Retraction is explicit and keeps a tombstone/history.

## 3. Environmental catalog and spatial storage — P02–P06

New `GET /api/map/layers` returns a small metadata object:

```json
{
  "data_mode": "live",
  "catalog_revision": "catalog-content-hash",
  "layers": [{
    "id": "huntsville_usfws_wetlands",
    "kind": "vector",
    "title": "Mapped wetlands",
    "category": "wetlands",
    "data_version": "source-and-scope-hash",
    "display_version": "derivative-config-hash",
    "delivery_status": "ready",
    "tile_url": "/api/map/layers/huntsville_usfws_wetlands/tiles/display-hash/{z}/{x}/{y}.pbf",
    "source_layer": "environment",
    "minzoom": 8,
    "maxzoom": 18,
    "bounds": [-87, 34, -86, 35],
    "coverage": {"status": "partial", "scope_id": "pilot-scope-version"},
    "source_name": "Authoritative source name",
    "source_url": "https://example.org/authoritative-source",
    "attribution": "Required source attribution",
    "data_as_of": null,
    "fetched_at": "2026-06-19T00:00:00Z",
    "default_visible": true
  }]
}
```

The example bounds and source URL are illustrative, not verified source facts. Counts, last success/attempt/error, freshness state and generalized-display caveat are additional metadata. `delivery_status`: unavailable, processing, ready, failed, withheld. Metadata is generated during ingestion/backfill, never by reading bulk geometry during an HTTP request. Catalog target <=50 KiB decoded; revalidate with ETag and a short TTL, initially 60 seconds. Never include private source fields. Relative tile templates resolve against the configured API origin, not the static website origin, and must preserve literal {z}/{x}/{y} tokens. Test the split-origin configuration, CORS and cache-header exposure explicitly.

Reuse/extend EnvironmentalLayer and EnvironmentalFeature for immutable canonical versions and original accepted EPSG:4326 geometry. One layer-version row owns its features, unique by stable source feature ID within that version. Maintain a small active-layer pointer by stable layer key. A separate derived display-parts table stores version/feature/zoom-band/part IDs and indexed EPSG:3857 geometry. Verify existing GeoAlchemy spatial indexes before adding another.

Canonical data_version includes source checksum + declared scope + canonical import format. display_version also includes derivative algorithm/config. Changes never overwrite bytes served under an existing version URL. Parsing/preprocessing runs offline; activate only complete validated data/derivatives in a short transaction. Retain active, previous and versions within at least seven days of replacement; extend retention if cache policy requires it. An old cached catalog must still work.

Tile path: `GET /api/map/layers/{layer_id}/tiles/{display_version}/{z}/{x}/{y}.pbf`. Fixed MVT source-layer `environment`, extent 4096, buffer 64. Validate 0 <= x,y < 2^z and catalog zoom range. Query projected indexed parts against the buffered envelope; do not transform the indexed column in the filter. Include only feature ID/category and required style properties. Success uses `application/vnd.mapbox-vector-tile`, immutable version caching and representation-correct ETags; errors use no-store. Empty tiles are valid 200 only for known ready versions.

On 410 from an expired tile version, the client revalidates the catalog once and switches to a ready current version; repeated failure remains visible instead of causing a request loop. A lightweight retired-version record distinguishes expiry from an unknown version.

Canonical geometry drives analysis. Display geometry may be simplified/subdivided and must never establish an environmental absence or be written back over originals. [PostGIS documents MVT generation](https://postgis.net/docs/ST_AsMVT.html) and the [geometry transform/clip contract](https://postgis.net/docs/ST_AsMVTGeom.html).

## 4. Development viewport read model — U00, P07, P08

Add `development_map_index` keyed by existing string public_id, with public summary fields, publication revision, original spatial geometry/centroid, bounded display geometry and GiST indexes. It is rebuilt from canonical records and synchronously updated by publication. A small dataset revision counter advances in the same transaction for any change affecting map results.

New `GET /api/map/developments?bbox=west,south,east,north&zoom=12&limit=500` uses the shared repeated filters. Bounds use longitude/latitude, finite values, west<east and south<north; reject antimeridian/global queries outside the supported pilot contract rather than guessing. Default limit 500, max 1,000. Query original geometry for exact inclusion; emit bounded display geometry with a declared representation (centroid or footprint).

Response is a GeoJSON FeatureCollection with foreign members `dataset_revision`, `total_matching`, `returned_count`, `next_cursor`, `truncated`, `truncation_reason` and query scope. Features have stable public_id IDs and only title/type/status/confidence/brief flag identifiers/publication revision/representation. No descriptions, raw source_fields or private contact data.

Order by public_id. Cursor encodes a versioned format, normalized query hash, dataset revision and last public_id; validate size/types/query match server-side. It grants no authorization. Read revision/count/page under one consistent database snapshot. A later page with an old revision returns 409 dataset_changed; client clears and restarts. Pages stop at both row and 512 KiB decoded limits, with a continuation cursor. Oversized single display footprints use a documented simpler representation, never dropped records.

Client accumulates at most 2,000 visible records then discloses a zoom/filter requirement. Details are fetched by existing record ID only when selected. P07 also adds `GET /api/map/developments/search?q=...&limit=20`, bounded local title/ID search; address indexing is optional only when already public. No universal geocoding promise.

## 5. Watch and delivery lifecycle — C07, S02, S03, C08

Watch states: pending_confirmation, active, unsubscribed. Legacy unverified watches are pending. C07 introduces this storage; C08 implements durable delivery with fixture messages and the local sink; S03 then adds the public confirmation/unsubscribe flow. Eligibility requires current active state and non-null confirmed_at <= event.occurred_at, preventing delayed matching from sending events that occurred before confirmation. Creation-time matches are a preview count, not automatic historical mail.

Matcher uses exact canonical geometry and validated filters. An event that leaves a watch area or retracts a previously matched record may notify prior matching subscriptions; do not notify unrelated watches. Baseline/context-only updates default to non-notifying.

Outbox key for development mail: watch_id + event_id + channel; confirmation jobs use message_kind + a separate idempotency key, with event_id nullable. Required fields include state, attempts, next_attempt_at, lease token/expiry, created/sent times and sanitized failure code. States: queued, leased, retry, sent, suppressed, dead. Insert matches and mark event handled atomically. Claims use short transactions and SKIP LOCKED; network sending is outside the transaction and completion compares the lease token.

Token records contain a hash, purpose, expiry and used_at. Confirmation expires after 24 hours. Any raw token required temporarily by a queued message is restricted, excluded from public/reviewer exports and cleared on send/expiry. Generated links use the public web origin and `/watch/confirm` or `/watch/unsubscribe`; pages call the separately configured API. GET does not change subscription state. POST does. Redact tokens from logs/referrers.

SMTP delivery is at-least-once. A crash after server acceptance can produce a duplicate despite deterministic Message-ID. Never claim exactly-once email. Recheck active status just before send, suppress unsubscribed watches and keep real delivery disabled until rehearsal.

## 6. Source coverage, safety and release behavior — D01, D02, O01–O04

Persist scope boundary/version, time window, source query, expected/fetched/accepted/rejected counts, coverage (complete/partial/failed/unknown), last successful data time and latest attempted refresh. Freshness and successful transport do not imply complete coverage. Before D01 implements scoped reconciliation, legacy/capped fetches are unknown or partial, with omitted coverage defaulting to unknown. Only proven complete observations may mark missing records source_missing with evidence; never infer cancelled or delete audit history. Partial/failed/unknown batches cannot retire missing records or replace a good environmental version as complete.

Use original geometries for PostGIS screening, with source/rule/record versions and unknown/partial outcomes outside reliable coverage. Context re-evaluation creates traceable non-notifying changes by default.

Public writes: default 256 KiB body cap, 2,000 vertices, strict finite coordinate/topology checks, explicit nullable staging locations, http/https source URLs and shared configurable quotas. Watch area initially <=2,500 km²; this is a pilot product limit, not a source fact. Trust forwarded client addresses only from configured proxies. Public schemas and event snapshots use allowlists.

Raw source artifacts must be uploaded and checksum-verified before hosted activation. Store source-use decisions separately from code licensing. Do not publish unresolved source content merely because it is accessible. Source terms/provider choices/root code license are release decisions prepared in O04; no fabricated permissions.

The release gate combines correctness, performance, live API workflows, fresh declared coverage, durable storage, restored backups, reviewer protection and observable failures. Deployment configuration and green mocked tests alone are insufficient.
