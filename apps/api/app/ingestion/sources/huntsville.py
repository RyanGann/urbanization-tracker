from __future__ import annotations

from app.ingestion.connectors.arcgis import ArcGISLayerConfig

HUNTSVILLE_GIS_ATTRIBUTION = "City of Huntsville GIS"

DATA_DEPOT_LICENSE_NOTE = (
    "Huntsville GIS Data Depot terms should be treated conservatively. Cache raw source "
    "payloads internally for audit/review, but do not expose public bulk mirrors until "
    "redistribution permission is clarified."
)

NEW_SUBDIVISIONS = ArcGISLayerConfig(
    key="huntsville_new_subdivisions",
    name="Huntsville New Subdivisions",
    service_url="https://maps.huntsvilleal.gov/server/rest/services/Housing/NewSubdivisions/MapServer",
    layer_id=0,
    source_type="arcgis_mapserver",
    source_agency=HUNTSVILLE_GIS_ATTRIBUTION,
    attribution=HUNTSVILLE_GIS_ATTRIBUTION,
    geometry_type="polygon",
    out_fields=(
        "SubdID",
        "Subdivision",
        "Phase",
        "Status",
        "HousingUnits",
        "HousingUnitType",
        "Layout_date",
        "Prelim_date",
        "Final_date",
        "AsBuilt_date",
        "CouncilDistrict",
        "CensusTract",
        "LegalName",
        "Public_Private",
        "TotalCertOfOcc",
        "PercentComplete",
        "SubdStatus",
        "SubdStatusDate",
        "SubdLots",
        "SubdUnits",
        "Type",
    ),
    order_by_fields="SubdID ASC",
    license_notes=DATA_DEPOT_LICENSE_NOTE,
    caveat="Primary polygon source for future development, with source status caveats.",
)

BUILDING_PERMITS = ArcGISLayerConfig(
    key="huntsville_building_permits",
    name="Huntsville Building Permits",
    service_url="https://maps.huntsvilleal.gov/server/rest/services/Licenses/BuildingPermits/MapServer",
    layer_id=0,
    source_type="arcgis_mapserver",
    source_agency=HUNTSVILLE_GIS_ATTRIBUTION,
    attribution=HUNTSVILLE_GIS_ATTRIBUTION,
    geometry_type="point",
    out_fields=(
        "PermitID",
        "AddressID",
        "Permit_Issue_DateTime",
        "Subdivision",
        "OccupancyType",
        "OccupancySubtype",
        "TypeOfWork",
        "DemolitionType",
        "NumberOfUnits",
        "BuildingSize",
        "ShowDetails",
        "ContractAmount",
        "CensusTract",
        "CouncilDistrict",
        "ActualCost",
    ),
    order_by_fields="Permit_Issue_DateTime DESC",
    max_records=500,
    license_notes=DATA_DEPOT_LICENSE_NOTE,
    caveat="Issued permit point context only; point geometry is not a development footprint.",
)

FEMA_FLOODPLAIN_1PCT = ArcGISLayerConfig(
    key="huntsville_fema_1pct_floodplain",
    name="Effective FEMA 1% Annual Chance Floodplain",
    service_url=(
        "https://maps.huntsvilleal.gov/server/rest/services/Flood/"
        "FEMA2018FloodInsuranceRateMap/MapServer"
    ),
    layer_id=7,
    source_type="arcgis_mapserver",
    source_agency="Federal Emergency Management Agency via City of Huntsville GIS",
    attribution="FEMA NFHL mirrored by Huntsville GIS",
    geometry_type="polygon",
    out_fields=("*",),
    result_record_count=2000,
    max_records=2000,
    category="floodplain",
    license_notes=DATA_DEPOT_LICENSE_NOTE,
    caveat="Floodplain context only; not a flood insurance, legal, or engineering determination.",
)

USFWS_WETLANDS = ArcGISLayerConfig(
    key="huntsville_usfws_wetlands",
    name="Mapped Wetlands",
    service_url="https://maps.huntsvilleal.gov/server/rest/services/NaturalResources/USFWSWetlands/MapServer",
    layer_id=0,
    source_type="arcgis_mapserver",
    source_agency="USFWS National Wetlands Inventory via City of Huntsville GIS",
    attribution="USFWS NWI mirrored by Huntsville GIS",
    geometry_type="polygon",
    out_fields=("*",),
    result_record_count=2000,
    max_records=2000,
    category="wetlands",
    license_notes=DATA_DEPOT_LICENSE_NOTE,
    caveat="Mapped wetland context only; not a jurisdictional wetland determination.",
)

DEVELOPMENT_SOURCES = (NEW_SUBDIVISIONS, BUILDING_PERMITS)
ENVIRONMENTAL_CONTEXT_SOURCES = (FEMA_FLOODPLAIN_1PCT, USFWS_WETLANDS)
ALL_SOURCES = DEVELOPMENT_SOURCES + ENVIRONMENTAL_CONTEXT_SOURCES
