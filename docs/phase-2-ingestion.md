# Source ingestion and identity recovery

Updated September 22, 2026. Source ingestion uses explicit live PostgreSQL storage.
Artifact-backed and demo previews remain supported for reading; they are not
identity-safe ingestion targets. The default local Compose preview uses demo mode.
Hosted ingestion remains disabled until the operational readiness gates are met.

The current ArcGIS workflow includes Huntsville subdivisions and building permits,
Madison County recorded subdivisions, and selected floodplain/wetland context.
Source-fetch commands perform network work; the implementation tests instead use
isolated fixture responses and disposable databases. Do not run a source refresh
merely to test a migration.

## Before ingesting an existing dataset

Set `DATA_MODE=live`, `PROCESSED_STORE_BACKEND=postgres`, and the connection to an
explicit copied database. Apply Alembic migrations to that copy. Preserve a custom
format PostgreSQL backup and the original raw artifacts. Never overwrite the
working snapshot while rehearsing migration.

From `apps/api`, using the locked Python environment:

```bash
python -m app.ingestion.cli backfill-source-identities > identity-dry-run.json
```

Review every candidate and diagnostic. The registry maps authoritative source IDs
to existing public IDs, preserving bookmarked URLs. It accepts numeric zero and
retains exact string IDs, including leading zeroes. Missing anchors, ambiguous
source mappings, duplicate public IDs and invalid discovery dates require explicit
resolution; title or location is not an identity substitute. Ordinary manual and
agenda records are outside this source-only backfill.

Apply only the reviewed report digest, then export the mapping:

```bash
python -m app.ingestion.cli backfill-source-identities \
  --apply-report-digest REVIEWED_REPORT_DIGEST \
  --mapping-export identity-mapping.json
```

The command rechecks the report under the canonical mutation lock and refuses
changed reports or unresolved diagnostics. A changed report requires a new dry run
and review. Re-run the dry run after application to verify no candidates remain.
Test the copied backup restore, mapping export and bookmarked record URLs before
considering any application against the working dataset.

## Source refresh behavior

The existing `ingest-huntsville` and `ingest-madison-county` CLI commands require
explicit live PostgreSQL mode and the ingestion enablement setting. Their
`--data-dir` selects private raw/run artifacts; it does not select the canonical
database. Configure and inspect the database connection separately. Enablement is
an operational decision, not a side effect of applying migrations.

Each source batch uses the shared transaction and source identity registry. A
name/status change updates the same public ID and preserves first discovery.
Unchanged replay retains identity. Missing/duplicate source IDs remain raw
evidence and are quarantined from canonical publication.

Legacy production fetches remain capped and have unknown or partial coverage
until D01 supplies scoped count reconciliation. Transport success and equal
reported/fetched counts do not establish completeness. Failed/partial/unknown
observations never retire missing records. An explicitly proven complete scoped
batch may record `source_missing`, but it preserves published history and does not
infer cancelled or completed status. Unrelated/manual records survive refreshes.

Canonical records, staging, retained raw observations, source health and legacy
environmental rows are stored in PostgreSQL. Raw download files, artifact manifest
entries and per-run summaries remain under the configured private data directory:

```text
raw/<source>/<run-id>.geojson
raw/<source>/latest.geojson
processed/artifact_manifest.json
runs/<run-id>.json
```

New source refreshes no longer rewrite the old canonical JSON snapshots. Existing
artifact preview reads and explicit maintenance imports are separate workflows.
An intended storage URI alone does not establish durable object storage; O01 owns
verified upload, audit and recovery.

## Retained raw observations

Historical observations are in `processed_collection_items` where
`collection_name = 'raw_records'`. Each row retains source/run provenance and a
payload checksum. The health `records.raw` count covers retained observations,
not only the latest incoming batch. Generic legacy artifact-file reads do not
represent these new database observations.

For a private diagnostic export, connect `psql` to the copied database using its
normal connection settings and write an explicit new output file:

```bash
psql --set=FETCH_COUNT=500 --tuples-only --no-align \
  --command="SELECT payload_json::text FROM processed_collection_items WHERE collection_name = 'raw_records' ORDER BY id" \
  > raw-observations.jsonl
```

This is private audit material, not a public bulk endpoint. A database backup
preserves these rows plus the identity registry, batches and observations. Preserve
raw files and their manifests separately until verified durable storage and a
combined restore rehearsal are complete.

## API and current limits

Live API reads require initialized stores; missing or corrupt live state returns
unavailable instead of silently substituting demo fixtures. Explicit demo mode is
isolated and labeled. The map uses `/api/map/layers` for metadata; environmental
controls remain unavailable until bounded layer delivery is implemented.

Source points are location context, not development footprints. Current proximity
flags remain screening information, not environmental absence or regulatory
determinations. No source coverage, deployment readiness, or alert-delivery
readiness is implied by this identity migration.
