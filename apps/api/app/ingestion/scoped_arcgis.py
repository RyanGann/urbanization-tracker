"""Bounded, non-publishing ArcGIS scope collection.

The caller must supply a reviewed polygon artifact.  This module only stages
observations; publication needs the durable-artifact gate owned by O01.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from shapely.errors import ShapelyError
from shapely.geometry import MultiPolygon, Polygon, shape

from app.ingestion.connectors.arcgis import ArcGISLayerConfig
from app.ingestion.source_merge import SourceBatch, SourceRecord
from app.ingestion.sources.huntsville import ALL_SOURCES as HUNTSVILLE_SOURCES
from app.ingestion.sources.madison_county import DEVELOPMENT_SOURCES as COUNTY_SOURCES

SOURCE_CONFIGS = {source.key: source for source in (*HUNTSVILLE_SOURCES, *COUNTY_SOURCES)}
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
MAX_GET_URL_BYTES = 1900


class ScopeError(ValueError):
    """The declared scope or source response cannot prove completeness."""


class BudgetExceeded(ScopeError):
    """A hard safety budget stopped collection."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _reject_nonfinite_constant(_value: str) -> Any:
    raise ScopeError("nonfinite_json_number")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ScopeError("nonfinite_json_number")
    return parsed


def _valid_polygon(value: Any) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("rings"), list):
        return False
    rings = value["rings"]
    if (not rings or len(rings) > 1000
        or sum(len(ring) for ring in rings if isinstance(ring, list)) > 100_000):
        return False
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
            return False
        for point in ring:
            if (
                not isinstance(point, list)
                or len(point) != 2
                or any(
                    not isinstance(axis, (int, float))
                    or isinstance(axis, bool)
                    for axis in point
                )
                or not -180 <= point[0] <= 180
                or not -90 <= point[1] <= 90
            ):
                return False
        if len({tuple(point) for point in ring[:-1]}) < 3:
            return False
    if value.get("spatialReference") != {"wkid": 4326}:
        return False
    try:
        # ArcGIS represents multipart polygons as a flat ring set. Build the
        # containment tree before checking topology so nested holes and islands
        # retain their intended parity without relying on ring orientation.
        outlines = [Polygon(ring) for ring in rings]
        if any(polygon.is_empty or not polygon.is_valid or polygon.area <= 0
               for polygon in outlines):
            return False
        parents: list[int | None] = []
        for index, polygon in enumerate(outlines):
            containers = [
                outer for outer, candidate in enumerate(outlines)
                if outer != index and candidate.area > polygon.area
                and candidate.contains(polygon)
            ]
            parents.append(min(containers, key=lambda outer: outlines[outer].area)
                           if containers else None)
        depths: list[int] = []
        for index in range(len(outlines)):
            depth = 0
            parent = parents[index]
            while parent is not None:
                depth += 1
                parent = parents[parent]
            depths.append(depth)
        components = [
            Polygon(rings[index], [
                rings[child] for child, parent in enumerate(parents)
                if parent == index and depths[child] % 2 == 1
            ])
            for index, depth in enumerate(depths) if depth % 2 == 0
        ]
        assembled = MultiPolygon(components)
        return not assembled.is_empty and assembled.is_valid
    except (TypeError, ValueError, OverflowError, ShapelyError):
        return False


@dataclass(frozen=True)
class ReviewedScope:
    version: str
    boundary: dict[str, Any]
    context: dict[str, Any]
    raw_boundary_response_sha256: str
    boundary_algorithm: str
    boundary_sha256: str
    context_sha256: str
    reviewed_at: str

    @classmethod
    def load(cls, path: Path) -> ReviewedScope:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != (
            "huntsville-city-limits-layer0-repaired-guard10-v1"
        ):
            raise ScopeError("scope_version_missing_or_unsupported")
        if payload.get("boundary_source_url") != (
            "https://maps.huntsvilleal.gov/server/rest/services/"
            "Boundaries/CityLimits/MapServer/0"
        ):
            raise ScopeError("boundary_source_mismatch")
        if payload.get("boundary_where") != "CityName = 'Huntsville'":
            raise ScopeError("boundary_selector_mismatch")
        if payload.get("source_srid") != 102629 or payload.get("context_buffer_m") != 510:
            raise ScopeError("boundary_crs_or_context_mismatch")
        raw_sha = payload.get("raw_boundary_response_sha256")
        if not isinstance(raw_sha, str) or len(raw_sha) != 64 or any(
            digit not in "0123456789abcdef" for digit in raw_sha
        ):
            raise ScopeError("raw_boundary_response_digest_missing")
        if payload.get("boundary_algorithm") != "ArcGIS-rings-ST_MakeValid-linework-v1":
            raise ScopeError("boundary_repair_algorithm_missing")
        boundary = payload.get("boundary_geometry")
        context = payload.get("context_geometry")
        if (not isinstance(boundary, dict) or not isinstance(context, dict)
            or not _valid_polygon(boundary) or not _valid_polygon(context)):
            raise ScopeError("invalid_scope_polygon")
        if _digest(boundary) != payload.get("boundary_sha256"):
            raise ScopeError("boundary_digest_mismatch")
        if _digest(context) != payload.get("context_sha256"):
            raise ScopeError("context_digest_mismatch")
        if payload.get("context_algorithm") != (
            "EPSG:5070-buffer-510m-for-500m-screening-v1"
        ):
            raise ScopeError("context_algorithm_mismatch")
        reviewed_at = payload.get("reviewed_at")
        if not isinstance(reviewed_at, str) or not reviewed_at:
            raise ScopeError("scope_not_reviewed")
        return cls(
            version=payload["version"],
            boundary=boundary,
            context=context,
            raw_boundary_response_sha256=raw_sha,
            boundary_algorithm=payload["boundary_algorithm"],
            boundary_sha256=payload["boundary_sha256"],
            context_sha256=payload["context_sha256"],
            reviewed_at=reviewed_at,
        )

    def geometry_for(self, config: ArcGISLayerConfig) -> dict[str, Any]:
        return self.context if config.category in {"floodplain", "wetlands"} else self.boundary

    def scope_id_for(self, config: ArcGISLayerConfig) -> str:
        # No implicit date predicate: all available permits intersecting the city
        # polygon are in scope.  Any later cutoff must produce a new scope ID.
        query = {
            "source": config.key, "where": config.where,
            "geometry": self.geometry_for(config),
            "relation": "esriSpatialRelIntersects", "time": None,
        }
        return f"{self.version}:{_digest(query)}"


@dataclass(frozen=True)
class CollectionBudget:
    max_requests: int = 1000
    max_ids: int = 100_000
    max_ids_bytes: int = 8 * 1024 * 1024
    max_response_bytes: int = 32 * 1024 * 1024
    max_staged_bytes: int = 1024 * 1024 * 1024
    max_seconds: float = 600
    max_attempts: int = 3
    min_interval_seconds: float = 0.1


class _Session:
    def __init__(
        self, client: httpx.Client, budget: CollectionBudget, *, sleep: Any = time.sleep
    ) -> None:
        self.client = client
        self.budget = budget
        self.sleep = sleep
        self.started = time.monotonic()
        self.last_request = 0.0
        self.requests = 0
        self.staged_bytes = 0
        self.retries = 0
        self.request_log: list[dict[str, Any]] = []

    def get(
        self, url: str, params: dict[str, str], *, byte_limit: int | None = None
    ) -> dict[str, Any]:
        cap = byte_limit or self.budget.max_response_bytes
        for attempt in range(self.budget.max_attempts):
            if self.requests >= self.budget.max_requests:
                raise BudgetExceeded("request_budget_exceeded")
            now = time.monotonic()
            if now - self.started >= self.budget.max_seconds:
                raise BudgetExceeded("time_budget_exceeded")
            if self.last_request:
                self.sleep(max(0.0, self.budget.min_interval_seconds - (now - self.last_request)))
            self.requests += 1
            self.last_request = time.monotonic()
            long_query = len(url) + len(urlencode(params)) > MAX_GET_URL_BYTES
            operation = (
                "metadata" if "returnCountOnly" not in params
                and "returnIdsOnly" not in params and "objectIds" not in params
                and "resultOffset" not in params else
                "count" if params.get("returnCountOnly") == "true" else
                "ids" if params.get("returnIdsOnly") == "true" else "geometry"
            )
            event: dict[str, Any] = {
                "url": url, "method": "POST" if long_query else "GET",
                "operation": operation, "query_sha256": _digest(params),
                "status": None, "response_bytes": 0,
            }
            self.request_log.append(event)
            try:
                # A full city polygon is too large for a URL. ArcGIS accepts
                # form-encoded POST for long read-only query operations.
                stream = (self.client.stream("POST", url, data=params) if long_query
                          else self.client.stream("GET", url, params=params))
                with stream as response:
                    event["status"] = response.status_code
                    if (
                        response.status_code in TRANSIENT_STATUS
                        and attempt + 1 < self.budget.max_attempts
                    ):
                        delay = _retry_delay(response.headers.get("Retry-After"), attempt)
                        self.retries += 1
                        self.sleep(delay)
                        continue
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        event["response_bytes"] += len(chunk)
                        self.staged_bytes += len(chunk)
                        if len(body) > cap:
                            raise BudgetExceeded("response_byte_budget_exceeded")
                        if self.staged_bytes > self.budget.max_staged_bytes:
                            raise BudgetExceeded("staged_byte_budget_exceeded")
                    response.raise_for_status()
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt + 1 >= self.budget.max_attempts:
                    raise ScopeError("transport_failure") from None
                self.retries += 1
                self.sleep(_retry_delay(None, attempt))
                continue
            try:
                payload = json.loads(
                    body, parse_constant=_reject_nonfinite_constant,
                    parse_float=_parse_finite_float,
                )
            except ScopeError:
                raise
            except (ValueError, UnicodeDecodeError) as exc:
                raise ScopeError("invalid_json_response") from exc
            if not isinstance(payload, dict):
                raise ScopeError("non_object_response")
            if isinstance(payload.get("error"), dict):
                raise ScopeError("arcgis_error_response")
            return payload
        raise ScopeError("transport_failure")


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    if retry_after is not None:
        try:
            return min(5.0, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return float(min(5.0, 0.25 * 2**attempt + random.uniform(0.0, 0.1)))


def _base_query(config: ArcGISLayerConfig, scope: ReviewedScope) -> dict[str, str]:
    return {
        "where": config.where,
        "geometry": _canonical(scope.geometry_for(config)).decode(),
        "geometryType": "esriGeometryPolygon",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
    }


def _oid_field(metadata: dict[str, Any], config: ArcGISLayerConfig) -> str:
    if metadata.get("geometryType") != {
        "point": "esriGeometryPoint", "polygon": "esriGeometryPolygon"
    }[config.geometry_type]:
        raise ScopeError("geometry_type_drift")
    formats = str(metadata.get("supportedQueryFormats", "")).lower()
    if "geojson" not in formats:
        raise ScopeError("geojson_not_supported")
    extent = metadata.get("extent")
    reference = extent.get("spatialReference") if isinstance(extent, dict) else None
    if not isinstance(reference, dict):
        reference = metadata.get("spatialReference")
    if not isinstance(reference, dict) or config.source_srid not in {
        reference.get("wkid"), reference.get("latestWkid"),
    }:
        raise ScopeError("source_crs_drift")
    fields = metadata.get("fields")
    if not isinstance(fields, list):
        raise ScopeError("fields_missing")
    field_names = {field.get("name") for field in fields if isinstance(field, dict)}
    required = set(config.out_fields) - {"*"}
    if not required.issubset(field_names):
        raise ScopeError("required_fields_missing")
    oid = metadata.get("objectIdField") or next(
        (field.get("name") for field in fields if isinstance(field, dict)
         and field.get("type") == "esriFieldTypeOID"), None
    )
    if not isinstance(oid, str) or oid not in field_names:
        raise ScopeError("object_id_field_missing")
    return oid


def _count(payload: dict[str, Any]) -> int:
    value = payload.get("count")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ScopeError("invalid_count")
    return value


def _ids(payload: dict[str, Any], oid_field: str, max_ids: int) -> list[int]:
    values = payload.get("objectIds")
    if not isinstance(values, list):
        raise ScopeError("invalid_id_response")
    if len(values) > max_ids:
        raise BudgetExceeded("id_budget_exceeded")
    if payload.get("objectIdFieldName") not in (None, oid_field):
        raise ScopeError("object_id_field_drift")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
        raise ScopeError("invalid_object_id")
    if len(set(values)) != len(values):
        raise ScopeError("duplicate_object_id")
    return sorted(values)


def _feature_id(feature: Any, oid_field: str) -> int:
    if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
        raise ScopeError("invalid_feature")
    value = feature["properties"].get(oid_field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ScopeError("feature_object_id_missing")
    return value


def _properties_ok(feature: dict[str, Any], config: ArcGISLayerConfig) -> bool:
    properties = feature.get("properties")
    return isinstance(properties, dict) and (
        "*" in config.out_fields
        or set(config.out_fields).issubset(properties)
    )


def _out_fields(config: ArcGISLayerConfig, oid_field: str) -> str:
    if "*" in config.out_fields:
        return "*"
    return ",".join(sorted(set(config.out_fields) | {oid_field}))


def _polygon_structure_ok(geometry: dict[str, Any]) -> bool:
    coordinates = geometry.get("coordinates")
    polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
    if not isinstance(polygons, list) or not polygons:
        return False
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            return False
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                return False
            if any(not isinstance(point, list) or len(point) != 2 for point in ring):
                return False
            if ring[0] != ring[-1] or len({tuple(point) for point in ring[:-1]}) < 3:
                return False
    return True


def _geometry_ok(feature: dict[str, Any], config: ArcGISLayerConfig) -> bool:
    geometry = feature.get("geometry")
    expected = {"Point"} if config.geometry_type == "point" else {"Polygon", "MultiPolygon"}
    if not isinstance(geometry, dict) or geometry.get("type") not in expected:
        return False
    from app.ingestion.geometry import iter_positions, validate_geometry

    try:
        if validate_geometry(geometry, expected):
            return False
        positions = list(iter_positions(geometry))
        if not positions or not all(
            math.isfinite(lon) and math.isfinite(lat)
            and -180 <= lon <= 180 and -90 <= lat <= 90
            for lon, lat in positions
        ):
            return False
        if config.geometry_type == "polygon":
            if not _polygon_structure_ok(geometry):
                return False
            parsed = shape(geometry)
            return not parsed.is_empty and parsed.is_valid
        return True
    except (TypeError, ValueError, IndexError, OverflowError, ShapelyError):
        return False


def _stage_page(
    payload: dict[str, Any], requested: list[int] | None, oid_field: str,
    config: ArcGISLayerConfig, destination: Path, report: dict[str, Any],
) -> list[int]:
    features = payload.get("features")
    if not isinstance(features, list):
        raise ScopeError("feature_list_missing")
    returned = [_feature_id(feature, oid_field) for feature in features]
    if len(returned) != len(set(returned)):
        raise ScopeError("duplicate_feature_object_id")
    if requested is not None and set(returned) != set(requested):
        raise ScopeError("batch_id_reconciliation_failed")
    page_number = len(report["pages"])
    page_path = destination / f"page-{page_number:05}.geojson"
    page_bytes = _canonical(payload)
    page_path.write_bytes(page_bytes)
    accepted = sum(
        _properties_ok(feature, config) and _geometry_ok(feature, config)
        for feature in features
    )
    report["pages"].append({
        "path": page_path.name,
        "sha256": hashlib.sha256(page_bytes).hexdigest(),
        "bytes": len(page_bytes), "requested": len(requested) if requested is not None else None,
        "returned": len(returned), "accepted": accepted,
        "rejected": len(returned) - accepted,
    })
    report["fetched"] += len(returned)
    report["accepted"] += accepted
    report["rejected"] += len(returned) - accepted
    return returned


def _offset_pages(
    session: _Session, config: ArcGISLayerConfig, scope: ReviewedScope,
    destination: Path, report: dict[str, Any], oid_field: str, metadata: dict[str, Any],
    *, canary: bool,
) -> None:
    capabilities = metadata.get("advancedQueryCapabilities")
    if not isinstance(capabilities, dict) or capabilities.get("supportsPagination") is not True:
        raise ScopeError("offset_pagination_not_supported")
    if capabilities.get("supportsOrderBy") is not True:
        raise ScopeError("stable_order_not_supported")
    base = _base_query(config, scope)
    page_size = 25 if canary else (250 if config.geometry_type == "point" else 32)
    expected = report["expected"]
    assert isinstance(expected, int)
    seen: set[int] = set()
    offset = 0
    while offset < expected:
        requested_count = min(page_size, expected - offset)
        params = {
            **base, "f": "geojson", "outFields": _out_fields(config, oid_field),
            "outSR": "4326", "returnGeometry": "true",
            "orderByFields": f"{oid_field} ASC",
            "resultOffset": str(offset),
            "resultRecordCount": str(requested_count),
        }
        payload = session.get(config.query_url, params)
        if isinstance(payload.get("features"), list) and len(payload["features"]) > requested_count:
            raise ScopeError("offset_page_oversized")
        returned = _stage_page(payload, None, oid_field, config, destination, report)
        if not returned or seen.intersection(returned):
            raise ScopeError("offset_page_repeated_or_empty")
        if returned != sorted(returned) or returned[0] <= max(seen, default=-1):
            raise ScopeError("offset_order_changed")
        seen.update(returned)
        offset += len(returned)
        if canary:
            return
    if len(seen) != expected:
        raise ScopeError("offset_count_reconciliation_failed")
    final_count = _count(session.get(
        config.query_url, {**base, "f": "json", "returnCountOnly": "true"}
    ))
    if final_count != expected:
        raise ScopeError("upstream_count_changed")
    start_edit = metadata.get("editingInfo", {}).get("lastEditDate") if isinstance(
        metadata.get("editingInfo"), dict
    ) else None
    final_metadata = session.get(config.layer_url, {"f": "json"})
    end_edit = final_metadata.get("editingInfo", {}).get("lastEditDate") if isinstance(
        final_metadata.get("editingInfo"), dict
    ) else None
    if start_edit is None or end_edit != start_edit:
        raise ScopeError("upstream_version_unproven_or_changed")
    report["reconciliation"] = {
        "method": "offset", "matched": True,
        "start_count": expected, "end_count": final_count,
        "start_edit_version": start_edit, "end_edit_version": end_edit,
        "unique_object_ids": len(seen), "query_sha256": _digest(base),
    }


def stage_scoped_source(
    config: ArcGISLayerConfig,
    scope: ReviewedScope,
    destination: Path,
    *,
    client: httpx.Client | None = None,
    budget: CollectionBudget | None = None,
    canary: bool = False,
) -> dict[str, Any]:
    """Stage page files and a coverage report without mutating canonical data."""
    if config.key not in SOURCE_CONFIGS:
        raise ScopeError("source_not_allowlisted")
    budget = budget or (
        CollectionBudget(max_requests=4, max_attempts=1, min_interval_seconds=1.0)
        if canary else CollectionBudget()
    )
    owned_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0), follow_redirects=True)
    session = _Session(client, budget)
    destination.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "source_key": config.key,
        "source_url": config.layer_url,
        "scope_id": scope.scope_id_for(config),
        "scope_version": scope.version,
        "raw_boundary_response_sha256": scope.raw_boundary_response_sha256,
        "boundary_algorithm": scope.boundary_algorithm,
        "boundary_sha256": scope.boundary_sha256,
        "context_sha256": scope.context_sha256 if config.category else None,
        "where": config.where,
        "time_window": None,
        "spatial_relation": "esriSpatialRelIntersects",
        "fetched_at": datetime.now(UTC).isoformat(),
        "coverage": "unknown",
        "expected": None,
        "fetched": 0,
        "accepted": 0,
        "rejected": 0,
        "pages": [],
        "canary": canary,
    }
    base = _base_query(config, scope)
    try:
        metadata = session.get(config.layer_url, {"f": "json"})
        fields = metadata.get("fields")
        extent = metadata.get("extent")
        reference = extent.get("spatialReference") if isinstance(extent, dict) else None
        report["source_metadata"] = {
            "geometry_type": metadata.get("geometryType"),
            "source_spatial_reference": reference,
            "field_names": sorted(
                field["name"] for field in fields
                if isinstance(field, dict) and isinstance(field.get("name"), str)
            ) if isinstance(fields, list) else None,
        }
        oid_field = _oid_field(metadata, config)
        report["object_id_field"] = oid_field
        count = _count(session.get(
            config.query_url, {**base, "f": "json", "returnCountOnly": "true"}
        ))
        report["expected"] = count
        if count > budget.max_ids:
            raise BudgetExceeded("id_budget_exceeded")
        if config.connector_config.get("pagination") == "offset":
            _offset_pages(session, config, scope, destination, report, oid_field, metadata,
                          canary=canary)
        else:
            initial_payload = session.get(
                config.query_url, {**base, "f": "json", "returnIdsOnly": "true"},
                byte_limit=budget.max_ids_bytes,
            )
            initial_ids = _ids(initial_payload, oid_field, budget.max_ids)
            if len(initial_ids) != count:
                raise ScopeError("count_id_mismatch")
            limit = 25 if canary else (250 if config.geometry_type == "point" else 32)
            ids_to_fetch = initial_ids[:limit] if canary else initial_ids
            for start in range(0, len(ids_to_fetch), limit):
                requested = ids_to_fetch[start:start + limit]
                payload = session.get(config.query_url, {
                    **base, "f": "geojson", "objectIds": ",".join(map(str, requested)),
                    "outFields": _out_fields(config, oid_field), "outSR": "4326",
                    "returnGeometry": "true",
                })
                _stage_page(payload, requested, oid_field, config, destination, report)
            if not canary:
                final_payload = session.get(
                    config.query_url, {**base, "f": "json", "returnIdsOnly": "true"},
                    byte_limit=budget.max_ids_bytes,
                )
                final_ids = _ids(final_payload, oid_field, budget.max_ids)
                if final_ids != initial_ids:
                    raise ScopeError("upstream_ids_changed")
                report["reconciliation"] = {
                    "method": "ids", "matched": True,
                    "start_ids_sha256": _digest(initial_ids),
                    "end_ids_sha256": _digest(final_ids),
                    "unique_object_ids": len(initial_ids),
                    "query_sha256": _digest(base),
                }
        if canary:
            report["coverage"] = "unknown"
        elif report["rejected"]:
            report["coverage"] = "partial"
        elif report["fetched"] == count:
            report["coverage"] = "complete"
    except (ScopeError, httpx.HTTPError, OSError) as exc:
        report["error_code"] = (
            str(exc) if isinstance(exc, ScopeError) else "transport_or_stage_failure"
        )
        report["coverage"] = (
            "partial" if isinstance(exc, BudgetExceeded) or report["fetched"] else "failed"
        )
    finally:
        report["requests"] = session.requests
        report["retries"] = session.retries
        report["response_bytes"] = session.staged_bytes
        report["request_log"] = session.request_log
        (destination / "report.json").write_bytes(_canonical(report) + b"\n")
        if owned_client:
            client.close()
    return report


def source_batch_from_staging(
    report: dict[str, Any], records: tuple[SourceRecord, ...],
    *, scope: ReviewedScope, page_sha256_assertions: set[str],
    report_sha256_assertion: str | None, run_id: str,
) -> SourceBatch:
    """Internal, non-publishing adapter for future O01/C03 integration.

    These caller-supplied digests are consistency assertions, not evidence of
    durable storage or an O01 sealed manifest. No production caller invokes this
    adapter until O01 store lookups, seal validation, and page normalization are
    integrated. This function cannot write canonical data by itself.
    """
    if report.get("canary"):
        raise ScopeError("canary_cannot_publish")
    try:
        report_digest = hashlib.sha256(_canonical(report) + b"\n").hexdigest()
    except (TypeError, ValueError, OverflowError) as exc:
        raise ScopeError("invalid_staged_report") from exc
    if report_sha256_assertion != report_digest:
        raise ScopeError("report_digest_assertion_mismatch")
    key = report.get("source_key")
    if key not in SOURCE_CONFIGS or report.get("scope_id") != scope.scope_id_for(
        SOURCE_CONFIGS[key]
    ) or report.get("scope_version") != scope.version:
        raise ScopeError("scope_identity_mismatch")
    if (report.get("raw_boundary_response_sha256") != scope.raw_boundary_response_sha256
        or report.get("boundary_algorithm") != scope.boundary_algorithm
        or report.get("boundary_sha256") != scope.boundary_sha256) or (
        SOURCE_CONFIGS[key].category and report.get("context_sha256") != scope.context_sha256
    ):
        raise ScopeError("scope_digest_mismatch")
    pages = report.get("pages")
    if not isinstance(pages, list) or (
        {page.get("sha256") for page in pages} != page_sha256_assertions
    ):
        raise ScopeError("page_digest_assertions_mismatch")
    expected = report.get("expected")
    fetched = report.get("fetched")
    accepted = report.get("accepted")
    rejected = report.get("rejected")
    if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0
               for value in (fetched, accepted, rejected)):
        raise ScopeError("invalid_staged_counts")
    assert isinstance(fetched, int) and isinstance(accepted, int) and isinstance(rejected, int)
    if accepted + rejected != fetched or len(records) > accepted:
        raise ScopeError("staged_counts_unreconciled")
    coverage = report.get("coverage")
    if coverage not in {"complete", "partial", "failed", "unknown"}:
        raise ScopeError("invalid_staged_coverage")
    if coverage == "complete" and (
        not isinstance(expected, int) or isinstance(expected, bool)
        or expected != fetched or rejected or len(records) != accepted
        or report.get("error_code")
    ):
        raise ScopeError("complete_coverage_unproven")
    if coverage == "complete":
        reconciliation = report.get("reconciliation")
        if not isinstance(reconciliation, dict) or reconciliation.get("matched") is not True:
            raise ScopeError("transport_reconciliation_missing")
        if reconciliation.get("query_sha256") != _digest(_base_query(SOURCE_CONFIGS[key], scope)):
            raise ScopeError("transport_query_mismatch")
        if reconciliation.get("unique_object_ids") != expected:
            raise ScopeError("transport_ids_unreconciled")
        method = reconciliation.get("method")
        if method == "ids":
            if not reconciliation.get("start_ids_sha256") or (
                reconciliation.get("start_ids_sha256") != reconciliation.get("end_ids_sha256")
            ):
                raise ScopeError("transport_ids_unreconciled")
        elif method == "offset":
            if reconciliation.get("start_count") != expected or (
                reconciliation.get("end_count") != expected
                or reconciliation.get("start_edit_version") is None
                or reconciliation.get("start_edit_version")
                != reconciliation.get("end_edit_version")
            ):
                raise ScopeError("transport_offset_unreconciled")
        else:
            raise ScopeError("transport_reconciliation_missing")
    if coverage == "failed" and records:
        raise ScopeError("failed_batch_has_records")
    try:
        checked_at = datetime.fromisoformat(str(report["fetched_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise ScopeError("invalid_fetched_at") from exc
    if checked_at.tzinfo is None:
        raise ScopeError("invalid_fetched_at")
    return SourceBatch(
        run_id=run_id,
        source_key=str(report["source_key"]),
        scope_id=str(report["scope_id"]),
        scope_version=str(report["scope_version"]),
        checked_at=checked_at,
        records=records,
        coverage=coverage,
        outcome="failed" if coverage == "failed" else "success",
        quarantined_count=rejected + accepted - len(records),
        expected_count=expected if isinstance(expected, int) else None,
        fetched_count=fetched,
        accepted_count=accepted,
        rejected_count=rejected,
        scope_metadata={
            "boundary_sha256": report.get("boundary_sha256"),
            "context_sha256": report.get("context_sha256"),
            "where": report.get("where"),
            "spatial_relation": report.get("spatial_relation"),
            "time_window": report.get("time_window"),
        },
    )


def scoped_attempt_health(existing: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Expose transport coverage while preserving the previous active-data time."""
    if report.get("canary"):
        raise ScopeError("canary_cannot_change_health")
    key = report.get("source_key")
    if key not in SOURCE_CONFIGS:
        raise ScopeError("source_not_allowlisted")
    sources = {
        str(source["key"]): source
        for source in existing.get("sources", [])
        if isinstance(source, dict) and source.get("key")
    }
    previous = sources.get(key, {})
    coverage = report.get("coverage")
    if coverage not in {"complete", "partial", "failed", "unknown"}:
        raise ScopeError("invalid_staged_coverage")
    row = {
        **previous,
        "key": key,
        "name": SOURCE_CONFIGS[key].name,
        "source_url": SOURCE_CONFIGS[key].layer_url,
        # A complete transport observation has still not passed the O01
        # durable-artifact and C03 canonical publication gates.
        "status": "staged" if coverage == "complete" else "failing",
        "coverage": previous.get("coverage", {"status": "unknown"}),
        "latest_attempt": {
            "status": coverage,
            "publication_status": "not_activated",
            "scope_id": report.get("scope_id"),
            "scope_version": report.get("scope_version"),
            "boundary_sha256": report.get("boundary_sha256"),
            "expected": report.get("expected"),
            "fetched": report.get("fetched"),
            "accepted": report.get("accepted"),
            "rejected": report.get("rejected"),
        },
        "checked_at": report.get("fetched_at"),
        "last_attempt_at": report.get("fetched_at"),
        "last_success_at": previous.get("last_success_at") or (
            previous.get("checked_at") if previous.get("status") == "healthy" else None
        ),
        "records_seen": report.get("fetched", 0),
        "records_created": previous.get("records_created", 0),
        "attempt_records_staged": report.get("accepted", 0),
        "error_count": int(bool(report.get("error_code") or report.get("rejected"))),
        "error_code": report.get("error_code"),
    }
    sources[key] = row
    return {
        **existing,
        "status": "degraded",
        "checked_at": report.get("fetched_at"),
        "sources": sorted(sources.values(), key=lambda source: str(source["key"])),
    }


def record_scoped_attempts(reports: list[dict[str, Any]]) -> None:
    """Short PostgreSQL write for attempt visibility; it publishes no source rows."""
    from app.config import get_settings
    from app.db import SessionLocal
    from app.transactional_store import CollectionUnitOfWork

    settings = get_settings()
    if settings.data_mode != "live" or settings.processed_store_backend != "postgres":
        raise ScopeError("scoped_health_requires_live_postgres")
    with SessionLocal.begin() as session:
        unit = CollectionUnitOfWork(session)
        with unit.canonical_mutation():
            health = unit.get_processed("source_health", "latest") or {
                "status": "unknown", "sources": [], "records": {},
            }
            for report in reports:
                health = scoped_attempt_health(health, report)
            unit.upsert_processed("source_health", "latest", health)
