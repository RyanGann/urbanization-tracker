from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from app.ingestion.geometry import approx_area_sq_m, centroid, validate_geometry
from app.ingestion.sources.huntsville import BUILDING_PERMITS, NEW_SUBDIVISIONS

SOURCE_CAVEAT = (
    "Public-source screening record. Verify source agency materials before making legal, "
    "permitting, ecological, engineering, flood insurance, or environmental-impact conclusions."
)


def normalize_development_feature(
    feature: dict[str, Any], source_key: str, checked_at: str
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    if source_key == NEW_SUBDIVISIONS.key:
        return normalize_new_subdivision(feature, checked_at)
    if source_key == BUILDING_PERMITS.key:
        return normalize_building_permit(feature, checked_at)
    raise ValueError(f"No normalizer configured for {source_key}")


def normalize_new_subdivision(
    feature: dict[str, Any], checked_at: str
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    properties = _properties(feature)
    geometry = feature.get("geometry") or {}
    validation_errors = validate_geometry(geometry, {"Polygon", "MultiPolygon"})
    subdivision = _string(properties.get("Subdivision")) or "Unnamed subdivision"
    phase = _string(properties.get("Phase"))
    source_status = _string(properties.get("Status")) or "Unknown"
    normalized_status = _subdivision_status(source_status)
    title = subdivision if not phase else f"{subdivision} {phase}"
    public_id = _public_id(
        "hsv-subdivision",
        properties.get("SubdID"),
        subdivision,
        phase,
        source_status,
    )
    record_centroid = centroid(geometry)

    staged = {
        "id": f"stage-{public_id}",
        "raw_record_id": _source_record_id(properties, fallback=public_id),
        "title": title,
        "description": _subdivision_description(properties),
        "development_type": "subdivision",
        "source_status": source_status,
        "normalized_status": normalized_status,
        "source_url": NEW_SUBDIVISIONS.layer_url,
        "source_agency": NEW_SUBDIVISIONS.source_agency,
        "date_discovered": checked_at[:10],
        "review_status": "approved",
        "record_confidence": "high" if not validation_errors else "medium",
        "geometry_source": "Huntsville New Subdivisions ArcGIS polygon",
        "geometry_confidence": "high",
        "geometry": geometry,
        "source_payload": properties,
        "normalization_notes": (
            "Auto-published from the Huntsville New Subdivisions polygon layer. "
            "Reviewer audit should still check naming and phase semantics."
        ),
        "validation_errors": validation_errors,
    }

    published = {
        "public_id": public_id,
        "title": title,
        "description": staged["description"],
        "development_type": "subdivision",
        "status": normalized_status,
        "source_status": source_status,
        "source_url": NEW_SUBDIVISIONS.layer_url,
        "source_agency": NEW_SUBDIVISIONS.source_agency,
        "date_discovered": checked_at[:10],
        "date_last_checked": checked_at[:10],
        "application_date": _arcgis_date(properties.get("Layout_date"))
        or _arcgis_date(properties.get("Prelim_date")),
        "approval_date": _arcgis_date(properties.get("Final_date")),
        "permit_issue_date": None,
        "review_status": "published",
        "confidence_level": staged["record_confidence"],
        "geometry_source": staged["geometry_source"],
        "geometry_confidence": staged["geometry_confidence"],
        "geometry": geometry,
        "centroid": record_centroid,
        "area_sq_m": approx_area_sq_m(geometry),
        "address": None,
        "parcel_ids": [],
        "source_fields": _public_source_fields(properties),
        "proximity_flags": [],
    }
    return staged, published, validation_errors


def normalize_building_permit(
    feature: dict[str, Any], checked_at: str
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    properties = _properties(feature)
    geometry = feature.get("geometry") or {}
    validation_errors = validate_geometry(geometry, {"Point"})
    permit_id = _string(properties.get("PermitID")) or _stable_hash(properties)
    title_bits = [
        _string(properties.get("Subdivision")),
        _string(properties.get("OccupancyType")),
        _string(properties.get("TypeOfWork")),
    ]
    title = " / ".join(bit for bit in title_bits if bit) or f"Building Permit {permit_id}"
    public_id = _public_id("hsv-building-permit", permit_id)
    record_centroid = centroid(geometry)

    staged = {
        "id": f"stage-{public_id}",
        "raw_record_id": _source_record_id(properties, fallback=permit_id),
        "title": title,
        "description": (
            "Issued building permit point context. Point geometry is not a parcel or "
            "development footprint."
        ),
        "development_type": "building_permit",
        "source_status": _string(properties.get("TypeOfWork")) or "Issued",
        "normalized_status": "issued_permit",
        "source_url": BUILDING_PERMITS.layer_url,
        "source_agency": BUILDING_PERMITS.source_agency,
        "date_discovered": checked_at[:10],
        "review_status": "approved",
        "record_confidence": "medium" if not validation_errors else "low",
        "geometry_source": "Huntsville Building Permits ArcGIS point",
        "geometry_confidence": "low",
        "geometry": geometry,
        "source_payload": properties,
        "normalization_notes": (
            "Auto-published as issued/current development context only. Do not treat point "
            "geometry as a development footprint."
        ),
        "validation_errors": validation_errors,
    }

    published = {
        "public_id": public_id,
        "title": title,
        "description": staged["description"],
        "development_type": "building_permit",
        "status": "issued_permit",
        "source_status": staged["source_status"],
        "source_url": BUILDING_PERMITS.layer_url,
        "source_agency": BUILDING_PERMITS.source_agency,
        "date_discovered": checked_at[:10],
        "date_last_checked": checked_at[:10],
        "application_date": None,
        "approval_date": None,
        "permit_issue_date": _arcgis_date(properties.get("Permit_Issue_DateTime")),
        "review_status": "published",
        "confidence_level": staged["record_confidence"],
        "geometry_source": staged["geometry_source"],
        "geometry_confidence": staged["geometry_confidence"],
        "geometry": geometry,
        "centroid": record_centroid,
        "area_sq_m": None,
        "address": None,
        "parcel_ids": [],
        "source_fields": _public_source_fields(properties),
        "proximity_flags": [],
    }
    return staged, published, validation_errors


def _subdivision_status(source_status: str) -> str:
    normalized = source_status.strip().lower()
    if normalized == "layout":
        return "layout"
    if normalized == "preliminary":
        return "preliminary"
    if normalized == "final":
        return "final"
    return "proposed"


def _subdivision_description(properties: dict[str, Any]) -> str:
    housing_units = properties.get("HousingUnits")
    unit_type = _string(properties.get("HousingUnitType"))
    status = _string(properties.get("Status")) or "source"
    if housing_units and unit_type:
        return f"{status} subdivision record with {housing_units} {unit_type.lower()}."
    return f"{status} subdivision record from the Huntsville New Subdivisions layer."


def _properties(feature: dict[str, Any]) -> dict[str, Any]:
    properties = feature.get("properties") or {}
    if not isinstance(properties, dict):
        return {}
    return properties


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _source_record_id(properties: dict[str, Any], fallback: str) -> str:
    for key in ("SubdID", "PermitID", "OBJECTID", "ObjectId", "FID"):
        value = _string(properties.get(key))
        if value:
            return value
    return fallback


def _public_source_fields(properties: dict[str, Any]) -> dict[str, Any]:
    blocked = {"Address"}
    return {key: value for key, value in properties.items() if key not in blocked}


def _public_id(prefix: str, *parts: Any) -> str:
    clean_parts = [_slug(str(part)) for part in parts if _string(part)]
    base = "-".join([prefix, *clean_parts])
    if len(base) <= 96:
        return base
    return f"{base[:80]}-{_stable_hash(parts)[:10]}"


def _slug(value: str) -> str:
    text = value.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "unknown"


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def _arcgis_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if re.match(r"^\d{4}-\d{2}-\d{2}", text):
            return text[:10]
        try:
            value = float(text)
        except ValueError:
            return text[:10]
    if isinstance(value, int | float):
        timestamp = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(timestamp, UTC).date().isoformat()
    return None
