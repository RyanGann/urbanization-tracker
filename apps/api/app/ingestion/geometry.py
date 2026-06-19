from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

Position = tuple[float, float]
BBox = tuple[float, float, float, float]
ProjectedPosition = tuple[float, float]
Segment = tuple[ProjectedPosition, ProjectedPosition]
ProjectedPolygon = list[list[ProjectedPosition]]
EPSILON = 1e-9


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


def geometries_intersect(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_projected, right_projected = _project_pair(left, right)
    return _projected_geometries_intersect(left_projected, right_projected)


def geometry_distance_m(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_projected, right_projected = _project_pair(left, right)
    if _projected_geometries_intersect(left_projected, right_projected):
        return 0.0
    return _projected_geometry_distance(left_projected, right_projected)


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


class _ProjectedGeometry:
    def __init__(self) -> None:
        self.points: list[ProjectedPosition] = []
        self.segments: list[Segment] = []
        self.polygons: list[ProjectedPolygon] = []


def _project_pair(
    left: dict[str, Any], right: dict[str, Any]
) -> tuple[_ProjectedGeometry, _ProjectedGeometry]:
    left_positions = list(iter_positions(left))
    right_positions = list(iter_positions(right))
    if not left_positions or not right_positions:
        raise ValueError("Geometry has no coordinates")
    origin_lon = sum(position[0] for position in [*left_positions, *right_positions]) / (
        len(left_positions) + len(right_positions)
    )
    origin_lat = sum(position[1] for position in [*left_positions, *right_positions]) / (
        len(left_positions) + len(right_positions)
    )
    meters_per_lon = 111_320 * math.cos(math.radians(origin_lat))
    meters_per_lat = 110_540

    def project(position: Position) -> ProjectedPosition:
        return (
            (position[0] - origin_lon) * meters_per_lon,
            (position[1] - origin_lat) * meters_per_lat,
        )

    return _to_projected_geometry(left, project), _to_projected_geometry(right, project)


def _to_projected_geometry(
    geometry: dict[str, Any],
    project: Any,
) -> _ProjectedGeometry:
    projected = _ProjectedGeometry()
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if coordinates is None:
        return projected

    if geometry_type == "Point":
        projected.points.append(project((float(coordinates[0]), float(coordinates[1]))))
    elif geometry_type == "MultiPoint":
        projected.points.extend(project(_position(coordinate)) for coordinate in coordinates)
    elif geometry_type == "LineString":
        _add_line(projected, [project(_position(coordinate)) for coordinate in coordinates])
    elif geometry_type == "MultiLineString":
        for line in coordinates:
            _add_line(projected, [project(_position(coordinate)) for coordinate in line])
    elif geometry_type == "Polygon":
        _add_polygon(projected, _project_rings(coordinates, project))
    elif geometry_type == "MultiPolygon":
        for polygon in coordinates:
            _add_polygon(projected, _project_rings(polygon, project))
    return projected


def _position(coordinate: list[float]) -> Position:
    return float(coordinate[0]), float(coordinate[1])


def _project_rings(rings: list[list[list[float]]], project: Any) -> ProjectedPolygon:
    return [[project(_position(coordinate)) for coordinate in ring] for ring in rings]


def _add_line(projected: _ProjectedGeometry, points: list[ProjectedPosition]) -> None:
    projected.points.extend(points)
    projected.segments.extend(_segments(points, closed=False))


def _add_polygon(projected: _ProjectedGeometry, rings: ProjectedPolygon) -> None:
    if not rings:
        return
    projected.polygons.append(rings)
    for ring in rings:
        projected.points.extend(ring)
        projected.segments.extend(_segments(ring, closed=True))


def _segments(points: list[ProjectedPosition], *, closed: bool) -> list[Segment]:
    if len(points) < 2:
        return []
    segments = [
        (points[index], points[index + 1])
        for index in range(len(points) - 1)
        if points[index] != points[index + 1]
    ]
    if closed and points[0] != points[-1]:
        segments.append((points[-1], points[0]))
    return segments


def _projected_geometries_intersect(
    left: _ProjectedGeometry, right: _ProjectedGeometry
) -> bool:
    if any(
        _points_equal(left_point, right_point)
        for left_point in left.points
        for right_point in right.points
    ):
        return True
    if any(
        _segments_intersect(left_segment, right_segment)
        for left_segment in left.segments
        for right_segment in right.segments
    ):
        return True
    if any(
        _point_on_segment(point, segment)
        for point in left.points
        for segment in right.segments
    ) or any(
        _point_on_segment(point, segment)
        for point in right.points
        for segment in left.segments
    ):
        return True
    if any(
        _point_in_polygon(point, polygon)
        for point in left.points
        for polygon in right.polygons
    ):
        return True
    return any(
        _point_in_polygon(point, polygon)
        for point in right.points
        for polygon in left.polygons
    )


def _projected_geometry_distance(left: _ProjectedGeometry, right: _ProjectedGeometry) -> float:
    minimum_distance = math.inf

    def track(distance: float) -> bool:
        nonlocal minimum_distance
        if distance < minimum_distance:
            minimum_distance = distance
        return minimum_distance <= EPSILON

    for left_point in left.points:
        for right_point in right.points:
            if track(_point_distance(left_point, right_point)):
                return 0.0

    for point in left.points:
        for segment in right.segments:
            if track(_point_segment_distance(point, segment)):
                return 0.0

    for point in right.points:
        for segment in left.segments:
            if track(_point_segment_distance(point, segment)):
                return 0.0

    for left_segment in left.segments:
        for right_segment in right.segments:
            if track(_segment_distance(left_segment, right_segment)):
                return 0.0

    return minimum_distance


def _segments_intersect(left: Segment, right: Segment) -> bool:
    left_a, left_b = left
    right_a, right_b = right
    left_orientation_a = _orientation(left_a, left_b, right_a)
    left_orientation_b = _orientation(left_a, left_b, right_b)
    right_orientation_a = _orientation(right_a, right_b, left_a)
    right_orientation_b = _orientation(right_a, right_b, left_b)

    if (
        left_orientation_a * left_orientation_b < 0
        and right_orientation_a * right_orientation_b < 0
    ):
        return True
    return (
        _collinear_and_on_segment(left_a, right_a, left_b, left_orientation_a)
        or _collinear_and_on_segment(left_a, right_b, left_b, left_orientation_b)
        or _collinear_and_on_segment(right_a, left_a, right_b, right_orientation_a)
        or _collinear_and_on_segment(right_a, left_b, right_b, right_orientation_b)
    )


def _orientation(
    left: ProjectedPosition,
    middle: ProjectedPosition,
    right: ProjectedPosition,
) -> float:
    return (middle[0] - left[0]) * (right[1] - left[1]) - (
        middle[1] - left[1]
    ) * (right[0] - left[0])


def _collinear_and_on_segment(
    start: ProjectedPosition,
    point: ProjectedPosition,
    end: ProjectedPosition,
    orientation: float,
) -> bool:
    return abs(orientation) <= EPSILON and _point_in_segment_bbox(point, (start, end))


def _point_on_segment(point: ProjectedPosition, segment: Segment) -> bool:
    return _collinear_and_on_segment(
        segment[0],
        point,
        segment[1],
        _orientation(segment[0], segment[1], point),
    )


def _point_in_segment_bbox(point: ProjectedPosition, segment: Segment) -> bool:
    start, end = segment
    return (
        min(start[0], end[0]) - EPSILON <= point[0] <= max(start[0], end[0]) + EPSILON
        and min(start[1], end[1]) - EPSILON <= point[1] <= max(start[1], end[1]) + EPSILON
    )


def _point_in_polygon(point: ProjectedPosition, polygon: ProjectedPolygon) -> bool:
    if not polygon:
        return False
    if any(
        _point_on_segment(point, segment)
        for ring in polygon
        for segment in _segments(ring, closed=True)
    ):
        return True
    if not _point_in_ring(point, polygon[0]):
        return False
    return not any(_point_in_ring(point, hole) for hole in polygon[1:])


def _point_in_ring(point: ProjectedPosition, ring: list[ProjectedPosition]) -> bool:
    inside = False
    if len(ring) < 3:
        return False
    x, y = point
    for start, end in _segments(ring, closed=True):
        y_between = (start[1] > y) != (end[1] > y)
        if not y_between:
            continue
        x_intersection = (end[0] - start[0]) * (y - start[1]) / (
            end[1] - start[1]
        ) + start[0]
        if x < x_intersection:
            inside = not inside
    return inside


def _segment_distance(left: Segment, right: Segment) -> float:
    if _segments_intersect(left, right):
        return 0.0
    return min(
        _point_segment_distance(left[0], right),
        _point_segment_distance(left[1], right),
        _point_segment_distance(right[0], left),
        _point_segment_distance(right[1], left),
    )


def _point_segment_distance(point: ProjectedPosition, segment: Segment) -> float:
    start, end = segment
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if abs(dx) <= EPSILON and abs(dy) <= EPSILON:
        return _point_distance(point, start)
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)
    clamped_t = max(0.0, min(1.0, t))
    projected = (start[0] + clamped_t * dx, start[1] + clamped_t * dy)
    return _point_distance(point, projected)


def _point_distance(left: ProjectedPosition, right: ProjectedPosition) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _points_equal(left: ProjectedPosition, right: ProjectedPosition) -> bool:
    return _point_distance(left, right) <= EPSILON


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
