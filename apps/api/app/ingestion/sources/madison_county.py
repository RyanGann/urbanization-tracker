from __future__ import annotations

from app.ingestion.connectors.arcgis import ArcGISLayerConfig

MADISON_COUNTY_GIS_ATTRIBUTION = "Madison County subdivisions via City of Huntsville GIS"

MADISON_COUNTY_SUBDIVISIONS = ArcGISLayerConfig(
    key="madison_county_subdivisions",
    name="Madison County Subdivisions",
    service_url=(
        "https://maps.huntsvilleal.gov/server/rest/services/Housing/"
        "SubdivisionsInMadisonCounty/MapServer"
    ),
    layer_id=0,
    source_type="arcgis_mapserver",
    source_agency=MADISON_COUNTY_GIS_ATTRIBUTION,
    attribution=MADISON_COUNTY_GIS_ATTRIBUTION,
    geometry_type="polygon",
    out_fields=(
        "OBJECTID",
        "Subd_Name",
        "Subd_Type",
        "Parcels",
        "Flag",
        "Book",
        "Page",
        "DocNum",
        "YearFiled",
        "DateFiled",
        "Subd_ID",
        "FilePath",
    ),
    order_by_fields="Subd_ID DESC",
    max_records=500,
    license_notes=(
        "Huntsville GIS Data Depot terms should be treated conservatively. Cache raw "
        "source payloads internally for audit/review, but do not expose public bulk mirrors "
        "until redistribution permission is clarified."
    ),
    caveat=(
        "Recorded subdivision polygon context. Treat as historical/subdivision record context, "
        "not as a current permit, engineering, title, or legal determination."
    ),
)

DEVELOPMENT_SOURCES = (MADISON_COUNTY_SUBDIVISIONS,)
