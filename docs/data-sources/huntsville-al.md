# Huntsville, Alabama Data Sources

Last updated: 2026-05-20

This document tracks candidate data sources for the Huntsville pilot. Future-development data is local, fragmented, and often needs reviewer validation.

## Summary Recommendation

Start with:

1. Huntsville New Subdivisions ArcGIS layer.
2. Huntsville Building Permits ArcGIS layer.
3. Huntsville Planning Commission agenda archive.

These provide a useful mix of polygon geometry, issued-permit point data, and proposed/approved agenda records.

## Phase 0 Verification Snapshot

Verified on 2026-05-20:

- Huntsville New Subdivisions and Building Permits ArcGIS REST services are reachable and queryable.
- Both ArcGIS services report ArcGIS Server `currentVersion` 11.3, support JSON/GeoJSON/PBF query output, and use source spatial reference `102629` with `esriFeet` units.
- `outSR=4326` works for JSON and GeoJSON queries, so ingestion can request WGS84 output directly and still retain source SRID/provenance.
- New Subdivisions has 327 polygon records. Observed `Status` counts: `Final` 240, `Layout` 29, `Preliminary` 58.
- Building Permits layer 0 has 17,778 point records with permit issue dates from 2020-11-02 through 2026-05-08. Layer 1 has 13,296 occupancy certificate point records.
- Planning Commission agenda PDFs from November 2025 through April 2026 were downloadable and text-extractable with `pdfjs-dist`.
- Agenda-to-subdivision matching is feasible for some names/phases but should be reviewer-gated because naming, spelling, and phase granularity are inconsistent.
- The pilot boundary is confirmed as the City of Huntsville corporate limits polygon from `Boundaries/CityLimits/MapServer`, layer 2.
- Local Huntsville GIS context layers have enough coverage for screening-level floodplain, hydrography, wetlands, parks/open space, greenway, zoning, land-use, slope, soil, sinkhole, stormwater, imagery, and parcel context.

## Local Sources

| Source | URL | Scope | Format/API | Freshness | License/Use Notes | MVP Difficulty |
|---|---|---|---|---|---|---|
| City of Huntsville GIS hub | https://www.huntsvilleal.gov/development/building-construction/gis/ | GIS entry point, maps, Data Depot, Data Gallery | Web pages, ArcGIS links | Maintained public page | General GIS portal; source-specific terms still matter | Low |
| Huntsville GIS Data Depot | https://www.huntsvilleal.gov/development/building-construction/gis/data-depot/ | Boundaries, floodplain, zoning, aerial imagery, base maps, DEM/TIN, metadata | Download portal | Maintained public portal | Page states data is copyrighted, free, no repackaging/reselling, no warranties. Need review before mirroring or redistributing. | Medium |
| Huntsville Building Permits | https://maps.huntsvilleal.gov/server/rest/services/Licenses/BuildingPermits/MapServer | Issued building permits and occupancy certificates | ArcGIS REST MapServer; JSON, GeoJSON, PBF | Live public service; observed permit dates through 2026-05-08 | Copyright text and item license are blank in service, but city data terms may apply | Medium |
| Huntsville New Subdivisions | https://maps.huntsvilleal.gov/server/rest/services/Housing/NewSubdivisions/MapServer | New subdivision polygons | ArcGIS REST MapServer; JSON, GeoJSON, PBF | Live public service; observed subdivision approval dates through March 2026 | Copyright text and item license are blank in service, but city data terms may apply | Low-medium |
| Huntsville Planning Commission | https://www.huntsvilleal.gov/development/building-construction/planning/planning-commission/ | Meeting info and current agenda | Web page plus PDF agendas | Agendas posted at least 24 hours before meetings according to page | Public meeting documents; parsing requires caution | Medium-high |
| Planning agenda archive | https://www.huntsvilleal.gov/planningagendas/ | Historical Planning Commission agendas/minutes | Web page plus PDF archive | Monthly | PDF extraction and reviewer validation required | High |
| Subdivision review page | https://www.huntsvilleal.gov/development/building-construction/planning/subdivision-review/ | Process context, forms, calendars | Web/PDF | Updated for annual calendars | Useful for interpreting statuses and schedule, not a record source by itself | Low |
| Building permit process page | https://www.huntsvilleal.gov/development/building-construction/building-license-permits/ | Permitting workflow context | Web/PDF links | Maintained public page | Useful for caveats and workflow interpretation | Low |
| Madison County ArcGIS services | https://madmaps1.madisonal.gov/server/rest/services | County GIS and planning context | ArcGIS REST | Public service | Needs source-by-source evaluation | Medium |

## Key Huntsville ArcGIS Layers

### Pilot Boundary

Service:

https://maps.huntsvilleal.gov/server/rest/services/Boundaries/CityLimits/MapServer

Confirmed Phase 0 boundary:

- Use layer 2, `City of Huntsville Area`, as the pilot boundary.
- Layer 1, `City of Huntsville Boundary`, is a polyline boundary useful for display but not for clipping/intersection.
- Layer 2 geometry: polygon in source SRID `102629`, StatePlane Alabama East feet.
- Query count tested: 1 record, `CityName = Huntsville`.
- Observed date fields: `Eff_Date` 2026-04-29 and `Mod_Date` 2026-04-30 from ArcGIS epoch date values.
- GeoJSON tested with `outSR=4326`; returned a `MultiPolygon`.

Boundary decision:

- The MVP pilot geography is the City of Huntsville corporate limits, not all of Madison County, the Huntsville metro area, or Huntsville-adjacent county service areas.
- Environmental/context analysis may use a buffer around the city boundary for proximity calculations, but records should be labeled as inside/outside the confirmed pilot boundary.
- Store this boundary internally as canonical pilot geometry with source URL, retrieval timestamp, source SRID, and transformed EPSG:4326 geometry.

### Building Permits

Service:

https://maps.huntsvilleal.gov/server/rest/services/Licenses/BuildingPermits/MapServer

Layer 0: `BuildingPermits`

- Geometry: point.
- Display field: `PermitID`.
- Supported query formats: JSON, GeoJSON, PBF.
- Max record count: 2000.
- Source spatial reference: `102629`, StatePlane Alabama East feet. The service advertises `esriFeet` units and WGS84/NAD83 datum transformations.
- Query result count tested: 17,778 records.
- Date coverage tested: `Permit_Issue_DateTime` from 2020-11-02T10:58:52Z through 2026-05-08T15:48:27Z.
- GeoJSON tested with `outSR=4326`; returned point coordinates as `[longitude, latitude]`.
- Observed `OccupancyType` values/counts: `Commercial` 2,946; `Condo` 31; `Duplex` 241; `Multi Apt` 2,722; `Single Family` 10,949; `Townhomes` 889.
- `exceededTransferLimit` appears when sampling with small `resultRecordCount`; use pagination with `resultOffset`/`resultRecordCount`.
- `HasZ: false`; `HasM: false`; attachments not advertised for this layer.

Useful fields:

| Field | Type | Notes |
|---|---|---|
| `PermitID` | integer | Display field and stable source identifier candidate. |
| `AddressID` | integer | Address-level source identifier. |
| `Permit_Issue_DateTime` | date | ArcGIS epoch milliseconds. |
| `Subdivision` | string(500) | Often populated for residential subdivision permits. |
| `OccupancyType` | string(20) | Renderer/category field. |
| `OccupancySubtype` | string(20) | Secondary category. |
| `TypeOfWork` | string(20) | Example values include alteration, demolition, new construction. |
| `DemolitionType` | string(20) | May contain padded strings. |
| `NumberOfUnits` | integer | Unit count where available. |
| `BuildingSize` | integer | Size field; observed zero for some sample rows. |
| `ShowDetails` | string(3) | Visibility/detail flag. |
| `Address` | string(255) | Street address; public display needs privacy/common-sense review. |
| `ContractAmount` | double | Cost-like field; may be null. |
| `CensusTract` | double | Numeric tract value. |
| `CouncilDistrict` | small integer | City council district. |
| `ActualCost` | double | Present on layer 0; may be null. |

Layer 1: `OccupancyCerts`

- Geometry: point.
- Query result count tested: 13,296 records.
- Similar fields, plus `Occupancy_Issue_DateTime` and `OccupancyNumber`.
- Use as post-permit completion/occupancy context, not as a future-development source.

Suggested use:

- Display as issued/current development context.
- Do not use point geometry as a definitive development footprint.
- For proximity flags, either mark as point-based low geometry confidence or wait for parcel/polygon enrichment.

### New Subdivisions

Service:

https://maps.huntsvilleal.gov/server/rest/services/Housing/NewSubdivisions/MapServer

Layer 0: `New Subdivisions`

- Geometry: polygon.
- Display field: `SUBDIVISION`.
- Supported query formats: JSON, GeoJSON, PBF.
- Max record count: 2000.
- Source spatial reference: `102629`, StatePlane Alabama East feet. The service advertises `esriFeet` units and WGS84/NAD83 datum transformations.
- Query result count tested: 327 records.
- GeoJSON tested with `outSR=4326`; returned polygon rings as `[longitude, latitude]`.
- Latest observed date fields: `Layout_date` 2026-02-24, `Prelim_date` 2026-03-24, `Final_date` 2026-03-24, `AsBuilt_date` 2026-03-02. `SubdStatusDate` was null in the aggregate max query.
- `HasZ: false`; `HasM: false`; attachments not advertised for this layer.
- Renderer/status values include:
  - `Layout`
  - `Preliminary`
  - `Final`

Useful fields:

| Field | Type | Notes |
|---|---|---|
| `SubdID` | integer | Source subdivision identifier candidate; not always unique by phase. |
| `Subdivision` | string(50) | Project/subdivision name. Query field uses this casing even though display field is reported as `SUBDIVISION`. |
| `Phase` | string(50) | Phase label; agenda text often uses variant abbreviations. |
| `Status` | string(50) | Renderer/status field: `Layout`, `Preliminary`, `Final`. |
| `HousingUnits` | small integer | Count paired with `HousingUnitType`. |
| `HousingUnitType` | string(6) | Observed values include lots and units. |
| `Layout_date` | date | ArcGIS epoch milliseconds. |
| `Prelim_date` | date | ArcGIS epoch milliseconds. |
| `Final_date` | date | ArcGIS epoch milliseconds. |
| `AsBuilt_date` | date | ArcGIS epoch milliseconds. |
| `CouncilDistrict` | small integer | City council district. |
| `CensusTract` | string(7) | Tract-like string. |
| `LegalName` | string(500) | Optional legal/project name. |
| `Public_Private` | string(7) | Optional public/private indicator. |
| `TotalCertOfOcc` | small integer | Optional occupancy certificate rollup. |
| `PercentComplete` | double | Optional completion metric. |
| `SubdStatus` | string(15) | Optional additional status field. |
| `SubdStatusDate` | date | Optional status date; aggregate query returned null. |
| `SubdLots` | small integer | Optional lot count. |
| `SubdUnits` | small integer | Optional unit count. |
| `Type` | string(30) | Development type such as single family. |

Suggested use:

- Primary MVP future-development layer.
- Use polygon geometry for proximity flags.
- Treat `Layout`, `Preliminary`, and `Final` as source statuses mapped into public status labels with definitions.

## Planning Commission Agenda PDFs

Current page:

https://www.huntsvilleal.gov/development/building-construction/planning/planning-commission/

Archive:

https://www.huntsvilleal.gov/planningagendas/

Inspected agenda PDFs:

| Meeting/archive label | PDF URL | Pages | Parseability notes |
|---|---|---:|---|
| April 28, 2026 | https://www.huntsvilleal.gov/wp-content/uploads/2026/04/Planning-Commission-Agenda-April-20206.pdf | 2 | Text extraction worked. Includes layout, preliminary, LCE, zoning, final, and bond sections. |
| March 24, 2026 | https://www.huntsvilleal.gov/wp-content/uploads/2026/03/Planning-Commission-Agenda-March-2026-1.pdf | 2 | Text extraction worked, but the PDF header says March 24, 2025 and minutes adoption says February 24, 2025; treat the archive label as source page metadata and retain the PDF text caveat. |
| February 24, 2026 | https://www.huntsvilleal.gov/wp-content/uploads/2026/02/Planning-Commission-Agenda-Feb-2026-2.pdf | 3 | Text extraction worked. Many subdivision items and zoning cases. |
| January 27, 2026 | https://www.huntsvilleal.gov/wp-content/uploads/2026/01/Planning-Commission-Agenda-January-2026-2.pdf | 2 | Text extraction worked. Includes minor subdivision, zoning, and final subdivision sections. |
| December 16, 2025 | https://www.huntsvilleal.gov/wp-content/uploads/2025/12/Planning-Commission-Agenda-December-2025-2.pdf | 4 | Text extraction worked. Includes layout/preliminary, zoning, apartment/final, bonds, and plat-vacation items. |
| November 18, 2025 | https://www.huntsvilleal.gov/wp-content/uploads/2025/11/Planning-Commission-Agenda-November2025-6.pdf | 3 | Text extraction worked. Includes LCE, zoning, preliminary/final subdivision, and bond items. |

Observed agenda fields include:

- Project name.
- Review type/status such as layout, preliminary, final, rezoning, LCE.
- Lots or units.
- Developer.
- Engineer/architect.
- General location.
- Proposed zoning.
- Meeting date.

Observed sections/categories include:

- Public hearings and presentations for approval.
- Location, character, and extent.
- Zoning.
- Apartments and subdivisions presented for final.
- Subdivision name changes.
- Invocation/extension of bonds.

Matching observations:

- Agenda items can sometimes be matched to New Subdivisions using normalized `Subdivision` plus `Phase`. Spot checks found matches for `Westmoore Landing Ph 1`, `Greenbrier Preserve / Maple Grove Ph 2`, `Greenbrier Preserve / Heritage Park`, `Martinson Ranch`, and `Tunlaw Ridge`.
- Some agenda items did not match with simple `LIKE` checks, including examples such as Bradford Crossing and Fennell Noble Industrial Park. They may be absent from the New Subdivisions layer, delayed, represented under another name, or present only after later approvals.
- Expect spelling variants and typos: examples include `SUBDIVISON`, `SUBDIVSIONS`, `Foutain`, `Arthitects`, and mixed phase abbreviations such as `Phase 1` versus `Ph 1`.
- Bond-extension and zoning-only items are useful context but should not automatically create future-development polygon records.

Suggested use:

- Fetch agenda page and PDF attachments.
- Store original PDFs.
- Extract text.
- Parse candidate agenda items into staging records.
- Require reviewer validation before publish.
- Geocode or match general location only with low confidence unless a reliable polygon/parcel match exists.

## Licensing and Caching Position

Working Phase 0 position, not legal advice:

- The GIS Data Depot page says City of Huntsville data is copyrighted, provided at no cost, and may not be repackaged or resold. It also disclaims warranties and says terms can change without notice.
- The tested ArcGIS services have blank `copyrightText`; tested item info has blank `licenseInfo`/`accessInformation`. That does not grant open redistribution rights.
- Treat live ArcGIS services as the authoritative public source. Cache raw ArcGIS responses internally for reproducibility, audit, deduplication, and reviewer workflow, but do not expose a public bulk download that recreates the city datasets until redistribution permission is clarified.
- Public records in the app should show source attribution, source URLs, retrieval timestamps, source status fields, and transformed/derived interpretation. Prefer linking to the source service/PDF over mirroring full source payloads publicly.
- Planning Commission agendas are public meeting documents, but PDF-derived records should remain staged until a reviewer confirms the parsed item, date, action/status, and geometry match.

## Local Environmental and Context Layers

The following Huntsville GIS services were inventoried during Phase 0. Counts are live ArcGIS `returnCountOnly` checks from 2026-05-20 where listed.

| Category | Source/service | Useful layers and tested counts | Geometry | Phase 0 decision |
|---|---|---|---|---|
| Pilot boundary | https://maps.huntsvilleal.gov/server/rest/services/Boundaries/CityLimits/MapServer | `City of Huntsville Area` layer 2: 1 | Polygon | Store as canonical pilot boundary. |
| Parcels | https://maps.huntsvilleal.gov/server/rest/services/Boundaries/CombinedParcels/MapServer | Limestone parcels: 66,856; Madison parcels: 200,044; Marshall parcels: 137; Morgan parcels: 76,807 | Polygon | Link live/defer bulk storage. Use only for reviewer lookup or future parcel enrichment after license/privacy review. |
| Utility/drainage easements | https://maps.huntsvilleal.gov/server/rest/services/Boundaries/PublicUtilityAndDrainageEasements/MapServer | Boundary and area layers | Polyline/polygon | Link live initially; not needed for MVP public screening flags. |
| Effective FEMA floodplain | https://maps.huntsvilleal.gov/server/rest/services/Flood/FEMA2018FloodInsuranceRateMap/MapServer | Floodway: 128; 1% annual chance floodplain: 1,883; 0.2% annual chance floodplain: 2,680 | Polygon plus supporting lines/points | Store clipped internal snapshot for reproducible floodplain flags; public UI should cite source and avoid flood-determination language. |
| Preliminary FEMA floodplain | https://maps.huntsvilleal.gov/server/rest/services/Flood/PreliminaryFEMAFloodInsuranceRateMap/MapServer | Preliminary floodway: 59; preliminary 100-year fringe: 1,046 | Polygon/polyline | Link or store separately from effective floodplain; label as preliminary, not authoritative. |
| Hydrography and streams | https://maps.huntsvilleal.gov/server/rest/services/NaturalResources/Hydrography/MapServer and https://maps.huntsvilleal.gov/server/rest/services/NaturalResources/StreamPolygons/MapServer | Hydrography lines: 27,336; stream polygons: 298 | Polyline/polygon | Store clipped/simplified internal snapshot for waterway proximity; cite local source and consider national NHD comparison later. |
| Drainage basins/watersheds | https://maps.huntsvilleal.gov/server/rest/services/NaturalResources/DrainageBasins/MapServer and https://maps.huntsvilleal.gov/server/rest/services/NaturalResources/PriorityWatersheds/MapServer | Subbasins: 509; major basins: 73; priority watersheds: 13 | Polygon | Store if used for context labels; lower priority than direct waterways/floodplain. |
| Wetlands | https://maps.huntsvilleal.gov/server/rest/services/NaturalResources/USFWSWetlands/MapServer | Wetlands: 18,195 | Polygon | Store clipped internal snapshot for proximity flags; cite USFWS/local mirror and state that this is not a jurisdictional wetland determination. |
| Parks, open space, greenways | https://maps.huntsvilleal.gov/server/rest/services/NaturalResources/OpenSpace/MapServer, https://maps.huntsvilleal.gov/server/rest/services/Recreation/Parks/MapServer, https://maps.huntsvilleal.gov/server/rest/services/Recreation/Greenways/MapServer | Open space: 1,911; parks: 157; greenways: 50; greenway plan: 234; hiking trails: 307; trailheads: 29 | Polygon/polyline/point | Store current parks/open-space/greenway features for context; keep planned greenways separate and clearly labeled. |
| Zoning and land use | https://maps.huntsvilleal.gov/server/rest/services/Zoning/ZoningDistricts/MapServer, https://maps.huntsvilleal.gov/server/rest/services/Zoning/ZoningGroups/MapServer, https://maps.huntsvilleal.gov/server/rest/services/NaturalResources/LandUse2024/MapServer, https://maps.huntsvilleal.gov/server/rest/services/NaturalResources/LandUseByZoning/MapServer | Zoning districts: 794; low-density zoning groups: 176; high-density zoning groups: 299; land use 2024: 11,710; land use by zoning: 794 | Polygon | Store internal snapshots only if needed for search/filter context; otherwise link live because zoning can change and is regulatory. |
| Slope, soils, sinkholes | https://maps.huntsvilleal.gov/server/rest/services/Zoning/SlopeDevelopmentDistricts/MapServer, https://maps.huntsvilleal.gov/server/rest/services/NaturalResources/NRCSSoils/MapServer, https://maps.huntsvilleal.gov/server/rest/services/NaturalResources/USGSPotentialSinkholes/MapServer | Slope lower: 515; slope upper: 43; NRCS soils: 40,568; septic-unsuitable soils: 24,620; potential sinkhole polygons: 4,803 | Polygon | Defer full ingestion. Link live or ingest clipped/simplified subsets only if a reviewer-facing caveat is written. |
| Stormwater infrastructure | https://maps.huntsvilleal.gov/server/rest/services/Tiled/Stormwater/MapServer | Flowlines: 34,521; waterbodies: 5,150; plus inlets, pipes, culverts, headwalls, proposed/abandoned groups | Point/polyline/polygon; tiled Web Mercator service | Link live/defer storage. Useful for reviewer context, but heavy and infrastructure-oriented rather than core MVP environmental screening. |
| Topography and imagery | https://maps.huntsvilleal.gov/server/rest/services/Tiled/Topography1FootElevationContours2019/MapServer, https://maps.huntsvilleal.gov/server/rest/services/Tiled/Topography5FootElevationContours2019/MapServer, https://maps.huntsvilleal.gov/server/rest/services/Tiled/AerialImagery2025/MapServer | 1-foot and 5-foot contours; 2025 aerial imagery | Polyline/raster; tiled Web Mercator services | Link live as basemap/context. Do not store imagery or contour tile caches in MVP. |

Store/link policy for local context:

- Store internally: pilot boundary, clipped floodplain polygons, clipped wetlands, clipped hydrography/stream features, selected watershed labels, and selected parks/open-space/greenway features needed for reproducible proximity flags.
- Store only with extra review: zoning, land use, slope districts, soils, sinkholes, species ranges, and parcel-derived enrichment.
- Link live/defer: full parcel layers, tiled aerial imagery, tiled topography, stormwater infrastructure, utility/drainage easements, and Data Depot downloads that would recreate city datasets.
- Public app output should expose derived flags, source names, source URLs, retrieval timestamps, and caveats, not a bulk mirror of Huntsville GIS layers.

## National and Federal Environmental Sources

| Source | URL | Use |
|---|---|---|
| Annual NLCD | https://www.mrlc.gov/data/project/annual-nlcd | Developed land and impervious-surface change |
| USGS hydrography products | https://www.usgs.gov/national-hydrography/access-national-hydrography-products | Waterways and watersheds |
| USFWS National Wetlands Inventory | https://www.fws.gov/program/national-wetlands-inventory/data-download | Wetland/deepwater context |
| FEMA NFHL | https://hazards.fema.gov/femaportal/wps/portal/NFHLWMS | Flood hazard context |
| USGS PAD-US | https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-download | Protected/public/conservation lands |
| USFWS Critical Habitat | https://services.arcgis.com/QVENGdaPbd4LUkLV/ArcGIS/rest/services/USFWS_Critical_Habitat/FeatureServer | Critical habitat context |
| USFWS refuge GIS tools | https://www.fws.gov/apps/service/national-wildlife-refuge-system-gis-data-and-mapping-tools | Wildlife refuge boundaries |

## Phase 0 Source Questions

- Can Huntsville ArcGIS layer data be cached and republished as derived public records? Working answer: internal caching is reasonable for audit/review; public bulk redistribution should wait for permission or counsel review.
- Do Data Depot terms apply to ArcGIS services, or only downloadable depot files? Unresolved; assume they may apply until confirmed otherwise.
- Is there a public metadata or license endpoint for each ArcGIS service? Item info exists but tested license/access fields are blank.
- Can new subdivision polygons be linked back to agenda items or planning cases? Partially. Name/phase matching works for some items but needs fuzzy matching and reviewer validation.
- Are permit records complete enough for public context, or are some fields intentionally restricted? Records are queryable, but permits should be treated as point context and not definitive footprints. Address/cost fields deserve product/privacy review before public display.
- Should Madison County services be included in the initial pilot or deferred? Deferred. The confirmed pilot boundary is City of Huntsville corporate limits; countywide services can be used later for context or expansion.
