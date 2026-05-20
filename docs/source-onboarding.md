# Source Onboarding

Use this checklist when adding a new city, county, or source.

## 1. Create A Jurisdiction Config

Add a JSON file in `apps/api/app/jurisdictions/`.

Required jurisdiction fields:

- `id`
- `name`
- `state`
- `country`
- `timezone`
- `default_center`
- `sources`

Required source fields:

- `key`
- `name`
- `connector_type`
- `parser_key`
- `source_url`
- `active`
- `privacy_review`
- `safety_review`

Supported connector types:

- `arcgis`
- `agenda_archive`
- `static_geojson`

The live Madison County config, `madison-county-al.json`, is the first real second-jurisdiction
source. The inactive `madison-county-al-demo.json` fixture remains as a parser/onboarding example.

## 2. Choose Or Add A Parser

Prefer existing parsers before adding new code:

- Huntsville New Subdivisions: `huntsville_new_subdivisions`
- Huntsville Building Permits: `huntsville_building_permits`
- Madison County Subdivisions: `madison_county_subdivisions`
- Planning agenda PDF: `huntsville_planning_agenda_pdf`
- Standard static GeoJSON: `standard_development_geojson`

If a source needs special fields, add a small parser that maps source payloads into staged records
with:

- source URL
- source agency
- source status
- normalized status
- record confidence
- geometry source
- geometry confidence
- public caveats

## 3. Run Safety Review

Complete [Privacy And Safety Checklist](privacy-safety-checklist.md) before turning on a source.

## 4. Verify

Run:

```bash
make lint
make typecheck
make test
make build
```

For ingestion sources, run the appropriate ingestion target and check:

- `GET /api/source-health`
- `GET /api/connector-health`
- reviewer queue source documents or staged records
- map rendering if the source publishes records

## 5. Public Display Rules

- Do not publish raw bulk mirrors by default.
- Link to authoritative source pages or service URLs.
- Hide or hash personal contact details.
- Keep low-confidence records reviewer-gated.
- State geometry caveats plainly.
- Treat environmental layers as screening context only.
