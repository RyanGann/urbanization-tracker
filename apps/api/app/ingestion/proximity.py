from __future__ import annotations

from typing import Any

from app.ingestion.connectors.arcgis import ArcGISLayerConfig
from app.ingestion.geometry import (
    bbox_distance_m,
    bboxes_intersect,
    geometries_intersect,
    geometry_bbox,
    geometry_distance_m,
)


def compute_proximity_flags(
    records: list[dict[str, Any]],
    environmental_collections: list[tuple[ArcGISLayerConfig, dict[str, Any]]],
) -> int:
    computed_count = 0
    environmental_features = [
        (config, feature, feature["geometry"], geometry_bbox(feature["geometry"]))
        for config, collection in environmental_collections
        for feature in collection.get("features", [])
        if feature.get("geometry")
    ]

    for record in records:
        if record["development_type"] != "subdivision" or not record.get("geometry"):
            continue
        record_geometry = record["geometry"]
        record_bbox = geometry_bbox(record_geometry)
        flags = record.setdefault("proximity_flags", [])
        seen_flag_types = {flag["flag_type"] for flag in flags}

        for config, feature, feature_geometry, feature_bbox in environmental_features:
            flag = _flag_for_relationship(
                record_geometry,
                record_bbox,
                config,
                feature,
                feature_geometry,
                feature_bbox,
            )
            if flag and flag["flag_type"] not in seen_flag_types:
                flags.append(flag)
                seen_flag_types.add(flag["flag_type"])
                computed_count += 1

    return computed_count


def _flag_for_relationship(
    record_geometry: dict[str, Any],
    record_bbox: tuple[float, float, float, float],
    config: ArcGISLayerConfig,
    feature: dict[str, Any],
    feature_geometry: dict[str, Any],
    feature_bbox: tuple[float, float, float, float],
) -> dict[str, Any] | None:
    if config.category == "floodplain":
        if not bboxes_intersect(record_bbox, feature_bbox):
            return None
        if not geometries_intersect(record_geometry, feature_geometry):
            return None
        return {
            "flag_type": "intersects_floodplain",
            "label": "Intersects effective FEMA 1% annual chance floodplain",
            "relationship": "intersects",
            "distance_m": 0,
            "threshold_m": 0,
            "method": "local_projected_geometry_intersection_epsg4326",
            "source_name": config.name,
            "source_url": config.layer_url,
            "source_feature_id": _feature_id(feature),
            "caveat": config.caveat or "",
        }

    if config.category == "wetlands" and bbox_distance_m(record_bbox, feature_bbox) <= 500:
        distance_m = geometry_distance_m(record_geometry, feature_geometry)
        if distance_m > 500:
            return None
        relationship = "intersects" if distance_m == 0 else "within"
        return {
            "flag_type": "near_wetland",
            "label": "Within 500 m of mapped wetlands",
            "relationship": relationship,
            "distance_m": round(distance_m, 1),
            "threshold_m": 500,
            "method": "local_projected_geometry_distance_epsg4326",
            "source_name": config.name,
            "source_url": config.layer_url,
            "source_feature_id": _feature_id(feature),
            "caveat": config.caveat or "",
        }

    return None


def _feature_id(feature: dict[str, Any]) -> str | None:
    properties = feature.get("properties") or {}
    for key in ("OBJECTID", "ObjectId", "FID", "WETLAND_ID"):
        value = properties.get(key)
        if value is not None:
            return str(value)
    return None
