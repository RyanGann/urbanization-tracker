# Phase 2 Ingestion

Last updated: 2026-05-20

Phase 2 adds a reproducible Huntsville ingestion workflow for:

- Huntsville New Subdivisions polygons.
- Recent Huntsville Building Permits point context.
- Effective FEMA 1% annual chance floodplain context.
- USFWS wetlands context through the Huntsville GIS mirror.

The command writes auditable local artifacts under `data/`, which is ignored by git:

- `data/raw/<source>/<run-id>.geojson`
- `data/raw/<source>/latest.geojson`
- `data/processed/raw_records.json`
- `data/processed/staged_development_records.json`
- `data/processed/development_records.json`
- `data/processed/environmental_overlays.json`
- `data/processed/source_health.json`
- `data/runs/<run-id>.json`

## Run Ingestion

```bash
make ingest-huntsville
```

Equivalent direct command:

```bash
cd apps/api
. .venv/bin/activate
python -m app.ingestion.cli ingest-huntsville --data-dir ../../data
```

Useful options:

```bash
python -m app.ingestion.cli ingest-huntsville \
  --data-dir ../../data \
  --permit-limit 500 \
  --context-limit 2000
```

## API Behavior

When processed ingestion artifacts exist, the API serves them from:

- `GET /api/development-records`
- `GET /api/map/development-records.geojson`
- `GET /api/development-records/{public_id}`
- `GET /api/environmental-overlays`
- `GET /api/reviewer/staged-records`
- `GET /api/source-health`

If no artifacts exist, the API falls back to Phase 1 seed/demo data.

## Current Method Limits

- New Subdivisions polygons are auto-published with high geometry confidence because the source provides polygons.
- Building Permits are auto-published as issued/current context with low geometry confidence because the source provides points, not footprints.
- Proximity flags use GeoJSON geometry intersection and local projected-meter distance checks, with
  bounding boxes retained only as a candidate prefilter. This is still screening-level context; a
  later normalized-table pass should move the same relationships into PostGIS
  `ST_Intersects`/`ST_Distance` queries.
- Wetlands are capped by `--context-limit`; the default stores only the first 2,000 features from the 18,195-record source.
- Raw source payloads are stored locally for audit/review, not exposed as public bulk downloads.
