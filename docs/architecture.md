# Urbanization Tracker Architecture

Last updated: 2026-05-20

## 1. Product Definition

Urbanization Tracker is a web-first, eventually mobile-capable, open-source public-good application. It helps people see where land is already developed, where future development is proposed or approved, and what environmental context exists nearby.

The application should be useful for residents, conservation groups, journalists, researchers, neighborhood associations, public-land advocates, and local reviewers who want a transparent, source-linked record of changing development activity.

### Core User Stories

- As a resident, I can see proposed, approved, active, and recently completed development near places I care about.
- As a conservation user, I can identify whether a development record is near wetlands, waterways, floodplains, protected lands, wildlife refuges, critical habitat, or recent impervious-surface growth.
- As a journalist or researcher, I can inspect source links, source documents, source agency, dates, confidence levels, geometry provenance, and review status for each record.
- As a reviewer, I can validate staged records, fix geometry interpretation, merge duplicates, and publish a reviewed record with an audit trail.
- As a maintainer, I can add a new local data connector without rewriting the ingestion system.

### Non-Goals

The app should not:

- Make legal determinations.
- Determine permit compliance.
- Perform wetland delineations.
- Make ESA consultation claims.
- Provide flood insurance determinations.
- Estimate property value.
- Publish definitive environmental-impact conclusions.
- Treat missing data as evidence that no development exists.
- Expose sensitive personal or ecological information beyond already-public source records.

### Misuse and Misinterpretation Risks

- Users may over-trust incomplete or stale local data.
- Point-only permits may imply more spatial certainty than the source supports.
- PDF-derived planning records may be parsed incorrectly without review.
- Environmental proximity flags may be mistaken for legal violations.
- Uneven local source coverage may make some jurisdictions look less developed simply because their data is harder to access.
- Applicant, owner, or contractor information may create privacy or harassment risks. The MVP should avoid presenting personal details unless clearly necessary and already central to the public record.

## 2. Pilot Geography

The first pilot is **City of Huntsville, Alabama**.

Huntsville is a strong pilot because it has:

- Public ArcGIS REST services for building permits.
- A public ArcGIS polygon layer for new subdivisions.
- Planning Commission agenda PDFs with proposed/approved development items.
- Local GIS data for boundaries, zoning, floodplain, hydrography, parks/open space, wetlands, and related context.
- Adjacent Madison County services that can be evaluated later.

The MVP should start with the city boundary and optionally include a small buffer for environmental context.

## 3. Data Feasibility

Future-development data should be treated as local and fragmented. There is no single reliable national source for proposed development.

### Candidate National and Federal Sources

| Category | Source | Likely Format | Freshness | Use Concern | Difficulty |
|---|---|---|---|---|---|
| Developed land and impervious surface | USGS/MRLC Annual NLCD | GeoTIFF, web services, downloads | Annual products | Raster resolution is coarse for parcel-level interpretation | Medium |
| Coastal land cover | NOAA C-CAP | Raster/downloads/services | Periodic | Coastal focus, may not be ideal for Huntsville | Medium |
| Waterways and watersheds | USGS National Hydrography products and Watershed Boundary Dataset | File geodatabase, shapefile, web services | Versioned/current products vary | NHD product transition requires care | Medium |
| Wetlands | USFWS National Wetlands Inventory | GeoPackage, file geodatabase, shapefile, WMS | Updated periodically | Not a jurisdictional wetland determination | Medium |
| Floodplains | FEMA National Flood Hazard Layer | ArcGIS REST, WMS/WFS, downloads | Updated as effective flood maps change | Not all areas equally modernized | Medium |
| Protected/public/conservation lands | USGS PAD-US | File geodatabase, web services | Versioned releases | Access and ownership fields need careful labeling | Medium |
| Critical habitat | USFWS Critical Habitat GIS services | ArcGIS REST/downloads | Maintained public service | Legal source is not the map service; sensitive interpretation | Medium |
| Wildlife refuges | USFWS refuge and cadastral boundaries | ArcGIS REST/downloads | Maintained public service | Not a survey boundary | Low-medium |
| Species context | USFWS IPaC, GBIF, NatureServe where appropriate | APIs/downloads/reports | Variable | Avoid precise/sensitive species-location claims | Medium-high |

### Candidate Huntsville Sources

Detailed source notes live in [Huntsville Data Sources](data-sources/huntsville-al.md).

Recommended first local sources:

1. Huntsville New Subdivisions ArcGIS layer - primary future-development polygon source.
2. Huntsville Building Permits ArcGIS layer - issued/current development point context.
3. Huntsville Planning Commission agenda archive - PDF source for proposed/approved items, reviewer-gated.

## 4. Technical Stack

### Frontend

- React
- TypeScript
- Vite
- MapLibre GL JS
- TanStack Query
- URL-addressable map state
- Playwright for E2E tests
- Vitest and Testing Library for component tests

The web app should be responsive and PWA-ready. Native mobile should wait until the data model, review workflow, and map UX are stable.

### Backend API

- FastAPI
- Pydantic schemas
- SQLAlchemy 2.x
- GeoAlchemy2
- Alembic migrations
- PostgreSQL/PostGIS
- pytest
- ruff
- mypy or pyright if type discipline remains manageable

FastAPI is a good fit if the project accepts that reviewer/admin tooling will be custom product work rather than inherited from Django Admin.

### Admin and Reviewer Workflow

Use a small custom internal reviewer UI rather than a generic full admin clone.

Phase 1 can use a protected internal route with:

- Staged records list.
- Record detail.
- Source payload/document view.
- Duplicate candidates.
- Geometry preview.
- Approve, reject, needs info, merge, and publish actions.

SQLAdmin or another lightweight FastAPI admin package may be useful for low-risk internal CRUD, but the core review queue should be custom because it needs provenance, geometry, confidence, and audit semantics.

### Database

Use PostgreSQL with PostGIS.

Recommended spatial strategy:

- Store canonical public geometries in EPSG:4326.
- Store raw source geometry and source SRID in separate geometry/provenance tables where useful.
- Transform Huntsville ArcGIS service geometries from StatePlane Alabama East feet where needed.
- Use geography or local projected geometry for distance calculations.
- Add GiST indexes to all published and staged geometries.

### Tile Strategy

Start simple:

- API returns GeoJSON for low-volume seed and pilot records.
- MapLibre renders records directly.

Scale path:

- Use Martin or pg_tileserv for dynamic PostGIS vector tiles.
- Generate PMTiles for stable clipped environmental layers.
- Put PMTiles behind CDN/object storage.

### Ingestion and Jobs

- Python ingestion package with Typer CLI.
- Connectors for ArcGIS REST, static downloads, open-data APIs, webpages, PDFs, and manual submissions.
- RQ plus Redis for scheduled/background jobs initially.
- Celery only if job orchestration becomes more complex.
- Cron or GitHub Actions can trigger low-frequency public-source checks early on.

### Deployment

Low-cost initial deployment:

- Docker Compose on a small VPS.
- Caddy or Nginx as reverse proxy.
- PostgreSQL/PostGIS with automated backups.
- Redis for worker queue.
- Cloudflare for DNS/CDN.
- Backblaze B2, Cloudflare R2, or S3-compatible object storage for source documents and generated tiles.

Managed services can be introduced later if maintenance burden grows.

## 5. Data Model

Every public development record should track:

- Source URL.
- Source agency.
- Date discovered.
- Date last checked.
- Confidence level.
- Geometry source.
- Status.
- Review status.
- Source document links.
- Ingestion run.
- Version/audit history.

### Core Entities

`agencies`

- `id`
- `name`
- `jurisdiction_name`
- `jurisdiction_type`
- `website_url`
- `contact_url`

`data_sources`

- `id`
- `agency_id`
- `name`
- `source_type`
- `base_url`
- `license_notes`
- `attribution`
- `update_cadence`
- `connector_key`
- `connector_config_json`
- `health_status`
- `last_success_at`
- `last_checked_at`

`ingestion_runs`

- `id`
- `data_source_id`
- `started_at`
- `finished_at`
- `status`
- `records_seen`
- `records_created`
- `records_updated`
- `records_skipped`
- `error_count`
- `log_uri`
- `source_window_start`
- `source_window_end`

`source_documents`

- `id`
- `data_source_id`
- `url`
- `title`
- `document_date`
- `fetched_at`
- `sha256`
- `content_type`
- `storage_uri`
- `extracted_text`
- `extraction_status`

`raw_records`

- `id`
- `data_source_id`
- `ingestion_run_id`
- `source_record_id`
- `payload_json`
- `fetched_at`
- `payload_sha256`

`staged_development_records`

- `id`
- `raw_record_id`
- `source_document_id`
- `title`
- `description`
- `development_type`
- `source_status`
- `normalized_status`
- `application_date`
- `approval_date`
- `permit_issue_date`
- `date_discovered`
- `date_last_checked`
- `source_url`
- `source_agency`
- `address`
- `parcel_ids`
- `geometry`
- `geometry_source`
- `geometry_confidence`
- `record_confidence`
- `review_status`
- `normalization_notes`

`development_records`

- `id`
- `public_id`
- `title`
- `description`
- `development_type`
- `status`
- `source_status`
- `source_url`
- `source_agency_id`
- `date_discovered`
- `date_last_checked`
- `application_date`
- `approval_date`
- `permit_issue_date`
- `review_status`
- `confidence_level`
- `geometry_source`
- `geometry_confidence`
- `canonical_geometry`
- `centroid`
- `area_sq_m`
- `address`
- `parcel_ids`
- `metadata_json`
- `created_at`
- `updated_at`

`record_geometries`

- `id`
- `development_record_id`
- `geometry`
- `geometry_role`
- `source_srid`
- `source_description`
- `confidence_level`
- `created_by`
- `created_at`

`map_layers`

- `id`
- `name`
- `category`
- `description`
- `source_id`
- `visibility_default`
- `min_zoom`
- `max_zoom`
- `tile_url`
- `attribution`
- `legend_json`

`environmental_layers`

- `id`
- `name`
- `category`
- `source_id`
- `version`
- `source_url`
- `loaded_at`
- `license_notes`
- `geom_type`

`environmental_features`

- `id`
- `environmental_layer_id`
- `source_feature_id`
- `name`
- `attributes_json`
- `geometry`

`proximity_flags`

- `id`
- `development_record_id`
- `environmental_layer_id`
- `flag_type`
- `relationship`
- `distance_m`
- `threshold_m`
- `method`
- `computed_at`
- `layer_version`

`review_events`

- `id`
- `record_id`
- `staged_record_id`
- `user_id`
- `event_type`
- `from_status`
- `to_status`
- `notes`
- `created_at`

`record_versions`

- `id`
- `development_record_id`
- `version_number`
- `snapshot_json`
- `changed_by`
- `changed_at`

`user_submissions`

- `id`
- `submitter_contact_hash`
- `title`
- `source_url`
- `notes`
- `geometry`
- `status`
- `created_at`

`watch_areas`

- `id`
- `user_id`
- `name`
- `geometry`
- `filters_json`
- `created_at`

`alerts`

- `id`
- `watch_area_id`
- `development_record_id`
- `alert_type`
- `sent_at`
- `status`

## 6. Ingestion Design

### Connector Types

ArcGIS REST connector:

- Reads service and layer metadata.
- Supports MapServer and FeatureServer query endpoints.
- Paginates using `resultOffset` and `resultRecordCount`.
- Requests GeoJSON where available.
- Falls back to Esri JSON and transforms geometries.
- Captures source layer fields and service metadata.

Static geospatial download connector:

- Supports shapefile ZIP, GeoPackage, GeoJSON, file geodatabase where GDAL supports it.
- Stores checksums.
- Loads into staging tables.
- Clips to pilot area where appropriate.

Open-data API connector:

- Supports Socrata, CKAN, CSV/JSON APIs, and source-specific APIs.
- Uses incremental fetch windows when available.
- Stores raw payloads before normalization.

Public webpage connector:

- Fetches public pages politely.
- Caches HTML.
- Extracts links to agendas, PDFs, detail pages, and attachments.
- Should be source-specific, not a fragile universal scraper.

PDF and agenda connector:

- Fetches agenda PDFs.
- Extracts text with PyMuPDF.
- Stores raw PDF and extracted text.
- Parses candidate items into staged records.
- Requires reviewer approval before publish.

Manual submission connector:

- Accepts public source links and optional drawn geometry.
- Creates staged records with low initial confidence.
- Requires review before publish.

### Pipeline Steps

1. Discover source records and documents.
2. Fetch raw payloads/documents.
3. Store immutable raw records with checksum.
4. Extract source fields and geometry.
5. Normalize into staging schema.
6. Validate required fields, dates, status, geometry validity, SRID, and source links.
7. Dedupe against source IDs, title/address, dates, and geometry overlap.
8. Route to review queue.
9. Reviewer approves, rejects, edits, or merges.
10. Publish canonical records.
11. Recompute environmental proximity flags.
12. Update map/search/tile outputs.

### Error Handling and Health

- Each source has a health status: healthy, degraded, failing, paused.
- Ingestion failures should not delete published records.
- Store raw errors and concise public health messages.
- Alert maintainers when a source schema changes, returns no records unexpectedly, or has repeated failures.
- Track `last_success_at`, `last_checked_at`, and record counts per run.

## 7. Map and UX Design

### Public Map Layers

Development:

- Proposed/planning.
- Layout/preliminary/final subdivisions.
- Issued permits.
- Active/in progress if source status supports it.
- Completed/occupancy certificates where useful.
- Withdrawn/expired if source status supports it.

Environmental:

- Wetlands.
- Waterways.
- Flood hazard areas.
- Watersheds.
- Protected/public/conservation lands.
- Wildlife refuges.
- Critical habitat.
- Impervious-surface change.

Context:

- Pilot boundary.
- City/county boundaries.
- Zoning and parcels only if license and privacy posture are acceptable.

### Filters

- Development status.
- Development type.
- Date range.
- Source agency.
- Confidence level.
- Review status.
- Geometry source.
- Environmental proximity flags.

### Popups and Detail Pages

Popups should show:

- Title.
- Status.
- Development type.
- Confidence badge.
- Geometry source.
- Source agency.
- Last checked date.
- Environmental flags.
- Link to detail page.

Detail pages should show:

- All source links.
- Source documents.
- Original source fields where safe.
- Review status and history.
- Geometry provenance.
- Environmental proximity calculations.
- Clear caveats about uncertainty and non-legal interpretation.

### Accessibility

- Provide a table/list alternative to the map.
- Ensure keyboard navigation for filters, records, and reviewer actions.
- Use color plus text/icon labels.
- Maintain contrast.
- Make popups usable on small screens.
- Use a bottom sheet pattern on mobile.
- Avoid hover-only interactions.

## 8. Environmental Proximity Flags

Use conservative flags, not a single impact score.

Initial flags:

- `near_wetland`: intersects, within 100 m, within 500 m.
- `near_waterway`: intersects, within 50 m, within 100 m.
- `intersects_floodplain`: intersects FEMA/local floodplain layer.
- `near_protected_area`: intersects or within 500 m.
- `near_refuge`: intersects or within 1 km.
- `near_critical_habitat`: intersects or within 1 km.
- `high_impervious_growth_context`: within a local area in the top quintile of impervious increase over a selected NLCD period.

Public label:

> Screening-level context only. This is not a legal, ecological, engineering, permitting, or environmental-impact determination.

## 9. Testing and Validation

Backend:

- Unit tests for Pydantic schemas, status normalization, confidence rules, and API filters.
- Integration tests for migrations, database repositories, and API endpoints.
- Geospatial tests for SRID transforms, `ST_MakeValid`, intersections, buffers, distances, and known fixture geometries.

Ingestion:

- Frozen HTTP fixtures for ArcGIS REST sources.
- PDF fixture tests for agenda parsing.
- Dedupe tests for source IDs, fuzzy names, dates, and overlapping geometries.
- Health monitoring tests for schema drift and partial failures.

Frontend:

- Component tests for filters, popups, layer toggles, and record detail pages.
- Playwright E2E tests for map load, filter flow, record detail, and reviewer publish flow.
- Accessibility checks with axe.

Suggested commands once code exists:

```bash
make lint
make typecheck
make test
make test-geo
make e2e
make build
docker compose up
```

## 10. Open Questions

- Does Huntsville permit caching, transforming, and republishing derived data from its ArcGIS services in an open-source public app?
- Should the MVP store local GIS layers or link/query them live?
- How much applicant/contractor/owner information should be shown publicly?
- Should permit points be buffered for proximity analysis, or should environmental flags be restricted to polygon-based sources until parcel geometry is available?
- Should Madison County be included in the first pilot boundary or treated as Phase 2 research?

