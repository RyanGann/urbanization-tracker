# Huntsville, Alabama Data Sources

Last updated: 2026-05-20

This document tracks candidate data sources for the Huntsville pilot. Future-development data is local, fragmented, and often needs reviewer validation.

## Summary Recommendation

Start with:

1. Huntsville New Subdivisions ArcGIS layer.
2. Huntsville Building Permits ArcGIS layer.
3. Huntsville Planning Commission agenda archive.

These provide a useful mix of polygon geometry, issued-permit point data, and proposed/approved agenda records.

## Local Sources

| Source | URL | Scope | Format/API | Freshness | License/Use Notes | MVP Difficulty |
|---|---|---|---|---|---|---|
| City of Huntsville GIS hub | https://www.huntsvilleal.gov/development/building-construction/gis/ | GIS entry point, maps, Data Depot, Data Gallery | Web pages, ArcGIS links | Maintained public page | General GIS portal; source-specific terms still matter | Low |
| Huntsville GIS Data Depot | https://www.huntsvilleal.gov/development/building-construction/gis/data-depot/ | Boundaries, floodplain, zoning, aerial imagery, base maps, DEM/TIN, metadata | Download portal | Maintained public portal | Page states data is copyrighted, free, no repackaging/reselling, no warranties. Need review before mirroring or redistributing. | Medium |
| Huntsville Building Permits | https://maps.huntsvilleal.gov/server/rest/services/Licenses/BuildingPermits/MapServer | Issued building permits and occupancy certificates | ArcGIS REST MapServer; JSON, GeoJSON, PBF | Public service, likely continuously updated | Copyright text blank in service, but city data terms may apply | Medium |
| Huntsville New Subdivisions | https://maps.huntsvilleal.gov/server/rest/services/Housing/NewSubdivisions/MapServer | New subdivision polygons | ArcGIS REST MapServer; JSON, GeoJSON, PBF | Public service, likely maintained as subdivision statuses change | Copyright text blank in service, but city data terms may apply | Low-medium |
| Huntsville Planning Commission | https://www.huntsvilleal.gov/development/building-construction/planning/planning-commission/ | Meeting info and current agenda | Web page plus PDF agendas | Agendas posted at least 24 hours before meetings according to page | Public meeting documents; parsing requires caution | Medium-high |
| Planning agenda archive | https://www.huntsvilleal.gov/planningagendas/ | Historical Planning Commission agendas/minutes | Web page plus PDF archive | Monthly | PDF extraction and reviewer validation required | High |
| Subdivision review page | https://www.huntsvilleal.gov/development/building-construction/planning/subdivision-review/ | Process context, forms, calendars | Web/PDF | Updated for annual calendars | Useful for interpreting statuses and schedule, not a record source by itself | Low |
| Building permit process page | https://www.huntsvilleal.gov/development/building-construction/building-license-permits/ | Permitting workflow context | Web/PDF links | Maintained public page | Useful for caveats and workflow interpretation | Low |
| Madison County ArcGIS services | https://madmaps1.madisonal.gov/server/rest/services | County GIS and planning context | ArcGIS REST | Public service | Needs source-by-source evaluation | Medium |

## Key Huntsville ArcGIS Layers

### Building Permits

Service:

https://maps.huntsvilleal.gov/server/rest/services/Licenses/BuildingPermits/MapServer

Layer 0: `BuildingPermits`

- Geometry: point.
- Display field: `PermitID`.
- Supported query formats: JSON, GeoJSON, PBF.
- Max record count: 2000.
- Source spatial reference: 102629, StatePlane Alabama East feet.
- Useful fields:
  - `PermitID`
  - `AddressID`
  - `Permit_Issue_DateTime`
  - `Subdivision`
  - `OccupancyType`
  - `OccupancySubtype`
  - `TypeOfWork`
  - `DemolitionType`
  - `NumberOfUnits`
  - `BuildingSize`
  - `Address`
  - `ContractAmount`
  - `CensusTract`
  - `CouncilDistrict`
  - `ActualCost`

Layer 1: `OccupancyCerts`

- Geometry: point.
- Similar fields, plus `Occupancy_Issue_DateTime` and `OccupancyNumber`.

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
- Source spatial reference: 102629, StatePlane Alabama East feet.
- Renderer/status values include:
  - `Layout`
  - `Preliminary`
  - `Final`
- Useful fields:
  - `SubdID`
  - `Subdivision`
  - `Phase`
  - `Status`
  - `HousingUnits`
  - `HousingUnitType`
  - `Layout_date`
  - `Prelim_date`
  - `Final_date`
  - `AsBuilt_date`
  - `CouncilDistrict`
  - `CensusTract`
  - `LegalName`
  - `Public_Private`
  - `TotalCertOfOcc`
  - `PercentComplete`
  - `SubdStatus`
  - `SubdStatusDate`
  - `SubdLots`
  - `SubdUnits`
  - `Type`

Suggested use:

- Primary MVP future-development layer.
- Use polygon geometry for proximity flags.
- Treat `Layout`, `Preliminary`, and `Final` as source statuses mapped into public status labels with definitions.

## Planning Commission Agenda PDFs

Current page:

https://www.huntsvilleal.gov/development/building-construction/planning/planning-commission/

Archive:

https://www.huntsvilleal.gov/planningagendas/

Observed agenda fields include:

- Project name.
- Review type/status such as layout, preliminary, final, rezoning, LCE.
- Lots or units.
- Developer.
- Engineer/architect.
- General location.
- Proposed zoning.
- Meeting date.

Suggested use:

- Fetch agenda page and PDF attachments.
- Store original PDFs.
- Extract text.
- Parse candidate agenda items into staging records.
- Require reviewer validation before publish.
- Geocode or match general location only with low confidence unless a reliable polygon/parcel match exists.

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

- Can Huntsville ArcGIS layer data be cached and republished as derived public records?
- Do Data Depot terms apply to ArcGIS services, or only downloadable depot files?
- Is there a public metadata or license endpoint for each ArcGIS service?
- Can new subdivision polygons be linked back to agenda items or planning cases?
- Are permit records complete enough for public context, or are some fields intentionally restricted?
- Should Madison County services be included in the initial pilot or deferred?

