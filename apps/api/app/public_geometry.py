"""Bounded public geometry validation; no coordinate repair or database fallback."""

from __future__ import annotations

import json
import math
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.public_rejections import record_public_rejection

MAX_VERTICES = 2_000


def invalid_geometry(message: str) -> HTTPException:
    record_public_rejection("invalid_geometry")
    return HTTPException(
        422, detail={"code": "invalid_geometry", "message": message, "field": "geometry"}
    )


def validate_geometry_structure(value: object, *, watch: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"type", "coordinates"}:
        raise ValueError("Geometry must contain only type and coordinates.")
    kind = value.get("type")
    allowed = {"Polygon", "MultiPolygon"} if watch else {"Point", "Polygon", "MultiPolygon"}
    if not isinstance(kind, str) or kind not in allowed:
        raise ValueError("Unsupported geometry type.")
    points: list[list[float]] = []

    def point(item: object) -> None:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("Coordinates must be two-dimensional longitude/latitude pairs.")
        if any(
            type(number) not in (int, float)
            or (isinstance(number, float) and not math.isfinite(number))
            for number in item
        ):
            raise ValueError("Coordinates must be finite numbers.")
        if not -180 <= item[0] <= 180 or not -90 < item[1] < 90:
            raise ValueError("Coordinates are outside the supported longitude/latitude range.")
        points.append(item)
        if len(points) > MAX_VERTICES:
            raise ValueError("Geometry exceeds the 2,000 vertex limit.")

    def polygon(item: object) -> None:
        if not isinstance(item, list) or not item:
            raise ValueError("A polygon requires at least one ring.")
        for ring in item:
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError("Each polygon ring requires at least four positions.")
            for position in ring:
                point(position)
            if ring[0] != ring[-1]:
                raise ValueError("Polygon rings must be explicitly closed.")

    coordinates = value["coordinates"]
    if kind == "Point":
        point(coordinates)
    elif kind == "Polygon":
        polygon(coordinates)
    else:
        if not isinstance(coordinates, list) or not coordinates:
            raise ValueError("A multipolygon requires at least one polygon.")
        for member in coordinates:
            polygon(member)
    # Pilot geometry has one unambiguous planar interpretation. Global/antimeridian
    # geometries need a separate contract before geography casts may accept them.
    if max(p[0] for p in points) - min(p[0] for p in points) >= 180:
        raise ValueError("Antimeridian-spanning geometry is not supported.")
    return value


def validate_public_geometry(geometry: dict[str, Any] | None, *, watch: bool = False) -> None:
    if geometry is None:
        if watch:
            raise invalid_geometry("A watch area requires a polygon.")
        return
    try:
        validate_geometry_structure(geometry, watch=watch)
    except ValueError as exc:
        raise invalid_geometry(str(exc)) from exc
    settings = get_settings()
    if settings.data_mode == "live" and settings.phase3_store_backend == "postgres":
        from app.db import SessionLocal

        try:
            with SessionLocal() as session:
                session.execute(text("SET LOCAL statement_timeout = '3000ms'"))
                row = session.execute(
                    text("""
                    WITH candidate AS (
                      SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326) AS geom
                    ) SELECT ST_IsValid(geom) AS valid,
                        CASE WHEN ST_IsValid(geom) THEN ST_Area(geom::geography) END AS area
                      FROM candidate
                """),
                    {"geometry": json.dumps(geometry, allow_nan=False)},
                ).one()
                valid, area = bool(row.valid), float(row.area or 0)
        except SQLAlchemyError as exc:
            raise HTTPException(
                503,
                detail={
                    "code": "geometry_validation_unavailable",
                    "message": "Location validation is unavailable. Please try again.",
                },
            ) from exc
    else:
        from pyproj import Geod
        from pyproj.exceptions import ProjError
        from shapely.errors import GEOSException
        from shapely.geometry import shape
        from shapely.geometry.polygon import orient

        try:
            candidate = shape(geometry)
            valid = bool(candidate.is_valid and not candidate.is_empty)
            area = 0.0
            if valid and candidate.geom_type != "Point":
                polygons = candidate.geoms if candidate.geom_type == "MultiPolygon" else [candidate]
                geod = Geod(ellps="WGS84")
                area = sum(
                    abs(geod.geometry_area_perimeter(orient(part, sign=1.0))[0])
                    for part in polygons
                )
        except (GEOSException, ProjError, ValueError, OverflowError) as exc:
            raise invalid_geometry(
                "Geometry could not be validated. Check its coordinates."
            ) from exc
    if not valid:
        raise invalid_geometry("Geometry has invalid polygon topology. Check edges and holes.")
    if watch and area > settings.public_watch_max_area_sq_km * 1_000_000:
        raise invalid_geometry(
            f"Watch area exceeds the {settings.public_watch_max_area_sq_km:g} km² limit."
        )


def require_publishable_geometry(record: dict[str, Any]) -> None:
    if record.get("geometry") is None:
        raise HTTPException(
            409,
            detail={
                "code": "location_required",
                "message": "A verified location is required before this record can be published.",
            },
        )
    validate_public_geometry(record["geometry"])
