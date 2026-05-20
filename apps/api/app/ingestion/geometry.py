from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

Position = tuple[float, float]
BBox = tuple[float, float, float, float]


def iter_positions(geometry: dict[str, Any]) -> Iterable[Position]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if coordinates is None:
        return

    if geometry_type == "Point":
        yield (float(coordinates[0]), float(coordinates[1]))
    elif geometry_type in {"LineString", "MultiPoint"}:
        for coordinate in coordinates:
            yield (float(coordinate[0]), float(coordinate[1]))
    elif geometry_type in {"Polygon", "MultiLineString"}:
        for ring in coordinates:
            for coordinate in ring:
                yield (float(coordinate[0]), float(coordinate[1]))
    elif geometry_type == "MultiPolygon":
        for polygon in coordinates:
            for ring in polygon:
                for coordinate in ring:
                    yield (float(coordinate[0]), float(coordinate[1]))


def geometry_bbox(geometry: dict[str, Any]) -> BBox:
    positions = list(iter_positions(geometry))
    if not positions:
        raise ValueError("Geometry has no coordinates")
    xs = [position[0] for position in positions]
    ys = [position[1] for position in positions]
    return min(xs), min(ys), max(xs), max(ys)


def centroid(geometry: dict[str, Any]) -> Position:
    positions = list(iter_positions(geometry))
    if not positions:
        raise ValueError("Geometry has no coordinates")
    lon = sum(position[0] for position in positions) / len(positions)
    lat = sum(position[1] for position in positions) / len(positions)
    return (round(lon, 7), round(lat, 7))


def approx_area_sq_m(geometry: dict[str, Any]) -> float | None:
    geometry_type = geometry.get("type")
    if geometry_type == "Polygon":
        return round(abs(_polygon_area_sq_m(geometry["coordinates"])))
    if geometry_type == "MultiPolygon":
        return round(
            sum(abs(_polygon_area_sq_m(polygon)) for polygon in geometry["coordinates"])
        )
    return None


def bbox_distance_m(left: BBox, right: BBox) -> float:
    if bboxes_intersect(left, right):
        return 0.0

    left_min_x, left_min_y, left_max_x, left_max_y = left
    right_min_x, right_min_y, right_max_x, right_max_y = right
    dx_degrees = max(right_min_x - left_max_x, left_min_x - right_max_x, 0)
    dy_degrees = max(right_min_y - left_max_y, left_min_y - right_max_y, 0)
    mean_lat = (left_min_y + left_max_y + right_min_y + right_max_y) / 4
    meters_per_lon = 111_320 * math.cos(math.radians(mean_lat))
    meters_per_lat = 110_540
    return math.hypot(dx_degrees * meters_per_lon, dy_degrees * meters_per_lat)


def bboxes_intersect(left: BBox, right: BBox) -> bool:
    return not (
        left[2] < right[0] or right[2] < left[0] or left[3] < right[1] or right[3] < left[1]
    )


def validate_geometry(geometry: dict[str, Any], expected_types: set[str]) -> list[str]:
    errors: list[str] = []
    geometry_type = geometry.get("type")
    if geometry_type not in expected_types:
        errors.append(f"Expected geometry type in {sorted(expected_types)}, got {geometry_type}")
        return errors
    try:
        geometry_bbox(geometry)
    except (TypeError, ValueError, IndexError) as exc:
        errors.append(f"Invalid geometry coordinates: {exc}")
    return errors


def _polygon_area_sq_m(rings: list[list[list[float]]]) -> float:
    if not rings:
        return 0
    shell = rings[0]
    if len(shell) < 4:
        return 0
    mean_lat = sum(point[1] for point in shell) / len(shell)
    meters_per_lon = 111_320 * math.cos(math.radians(mean_lat))
    meters_per_lat = 110_540
    points = [(point[0] * meters_per_lon, point[1] * meters_per_lat) for point in shell]
    area = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        area += point[0] * next_point[1] - next_point[0] * point[1]
    return area / 2
