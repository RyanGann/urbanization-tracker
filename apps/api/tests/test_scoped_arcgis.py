from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from app.ingestion.pipeline import _aggregate_status
from app.ingestion.scoped_arcgis import (
    CollectionBudget,
    ReviewedScope,
    ScopeError,
    _digest,
    _geometry_ok,
    scoped_attempt_health,
    source_batch_from_staging,
    stage_scoped_source,
)
from app.ingestion.source_merge import SourceRecord
from app.ingestion.sources.huntsville import BUILDING_PERMITS, NEW_SUBDIVISIONS

POLYGON = {
    "rings": [[[-87.0, 34.0], [-86.0, 34.0], [-86.0, 35.0], [-87.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}
CONFIG = replace(BUILDING_PERMITS, out_fields=("PermitID",), max_records=None)


def _scope(tmp_path: Path) -> ReviewedScope:
    path = tmp_path / "reviewed-scope.json"
    path.write_text(
        json.dumps(
            {
                "version": "huntsville-city-limits-layer0-repaired-guard10-v1",
                "boundary_source_url": (
                    "https://maps.huntsvilleal.gov/server/rest/services/"
                    "Boundaries/CityLimits/MapServer/0"
                ),
                "boundary_where": "CityName = 'Huntsville'",
                "source_srid": 102629,
                "raw_boundary_response_sha256": "0" * 64,
                "boundary_algorithm": "ArcGIS-rings-ST_MakeValid-linework-v1",
                "boundary_geometry": POLYGON,
                "boundary_sha256": _digest(POLYGON),
                "context_geometry": POLYGON,
                "context_sha256": _digest(POLYGON),
                "context_buffer_m": 510,
                "context_algorithm": "EPSG:5070-buffer-510m-for-500m-screening-v1",
                "reviewed_at": "2026-09-22T00:00:00Z",
            }
        ), encoding="utf-8"
    )
    return ReviewedScope.load(path)


def _feature(object_id: int, *, valid: bool = True) -> dict[str, object]:
    return {
        "type": "Feature", "properties": {"OBJECTID": object_id, "PermitID": object_id},
        "geometry": {"type": "Point", "coordinates": [-86.5, 34.5]}
        if valid else {"type": "Point", "coordinates": []},
    }


def _fixture(
    ids: list[int], *, second_ids: list[int] | None = None,
    count: object | None = None, batch_override: list[dict[str, object]] | None = None,
    transient: bool = False, raw_page: bytes | None = None,
) -> tuple[httpx.MockTransport, list[dict[str, str]]]:
    requests: list[dict[str, str]] = []
    id_queries = 0
    transient_once = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal id_queries, transient_once
        encoded = request.content if request.method == "POST" else request.url.query
        params = {key: values[0] for key, values in parse_qs(encoded.decode()).items()}
        params["__method"] = request.method
        requests.append(params)
        if transient and not transient_once and params.get("returnCountOnly") == "true":
            transient_once = True
            return httpx.Response(429, headers={"Retry-After": "0"})
        if str(request.url).split("?")[0].endswith("/0"):
            return httpx.Response(200, json={
                "geometryType": "esriGeometryPoint", "supportedQueryFormats": "JSON, geoJSON",
                "extent": {"spatialReference": {"wkid": 102629}},
                "objectIdField": "OBJECTID", "fields": [
                    {"name": "OBJECTID", "type": "esriFieldTypeOID"},
                    {"name": "PermitID", "type": "esriFieldTypeInteger"},
                ],
            })
        if params.get("returnCountOnly") == "true":
            return httpx.Response(200, json={"count": len(ids) if count is None else count})
        if params.get("returnIdsOnly") == "true":
            id_queries += 1
            return httpx.Response(200, json={
                "objectIdFieldName": "OBJECTID",
                "objectIds": second_ids if id_queries > 1 and second_ids is not None else ids,
            })
        requested = [int(value) for value in params["objectIds"].split(",")]
        if raw_page is not None:
            return httpx.Response(200, content=raw_page)
        features = (
            batch_override
            if batch_override is not None
            else [_feature(value) for value in requested]
        )
        return httpx.Response(200, json={"type": "FeatureCollection", "features": features})

    return httpx.MockTransport(handler), requests


def _run(
    tmp_path: Path, transport: httpx.MockTransport, *, canary: bool = False
) -> dict[str, object]:
    with httpx.Client(transport=transport) as client:
        return stage_scoped_source(
            CONFIG, _scope(tmp_path), tmp_path / "stage", client=client, canary=canary,
            budget=CollectionBudget(
                max_requests=4 if canary else 1000, max_attempts=1 if canary else 3,
                min_interval_seconds=0,
            ),
        )


def test_scoped_ids_stream_pages_and_reconcile(tmp_path: Path) -> None:
    transport, requests = _fixture(list(range(501)))
    report = _run(tmp_path, transport)
    assert report["coverage"] == "complete"
    assert (report["expected"], report["fetched"], report["accepted"]) == (501, 501, 501)
    assert len(report["pages"]) == 3
    assert len(requests) == 7  # metadata, count, IDs, three pages, re-enumeration
    scoped = [
        request for request in requests
        if "returnCountOnly" in request or "returnIdsOnly" in request or "objectIds" in request
    ]
    scope_params = {(r["where"], r["geometry"], r["spatialRel"]) for r in scoped}
    assert len(scope_params) == 1
    assert all("resultOffset" not in request for request in scoped)


@pytest.mark.parametrize(
    ("ids", "count", "batch", "expected_error"), [
        ([1, 2], 3, None, "count_id_mismatch"),
        ([1, 1], None, None, "duplicate_object_id"),
        ([1, 2], None, [_feature(1)], "batch_id_reconciliation_failed"),
        ([1, 2], None, [_feature(1), _feature(1)], "duplicate_feature_object_id"),
        ([1], False, None, "invalid_count"),
    ],
)
def test_bad_reconciliation_never_completes(
    tmp_path: Path, ids: list[int], count: object | None,
    batch: list[dict[str, object]] | None, expected_error: str,
) -> None:
    transport, _ = _fixture(ids, count=count, batch_override=batch)
    report = _run(tmp_path, transport)
    assert report["error_code"] == expected_error
    assert report["coverage"] == "failed"


def test_upstream_change_and_rejected_geometry(tmp_path: Path) -> None:
    transport, _ = _fixture([1], second_ids=[2])
    changed = _run(tmp_path, transport)
    assert changed["error_code"] == "upstream_ids_changed"
    assert changed["coverage"] == "partial"
    transport, _ = _fixture([1], batch_override=[_feature(1, valid=False)])
    invalid = _run(tmp_path, transport)
    assert invalid["coverage"] == "partial"
    assert invalid["rejected"] == 1


def test_missing_required_source_property_cannot_complete(tmp_path: Path) -> None:
    feature = _feature(1)
    feature["properties"] = {"OBJECTID": 1}
    transport, _ = _fixture([1], batch_override=[feature])
    report = _run(tmp_path, transport)
    assert report["coverage"] == "partial"
    assert (report["fetched"], report["accepted"], report["rejected"]) == (1, 0, 1)


@pytest.mark.parametrize("coordinates", [
    [[[0, 0], [1, 0], [0, 0]]],  # Too few ring positions.
    [[[0, 0], [1, 0], [0, 1], [1, 1]]],  # Open ring.
    [[]],  # Empty ring inside an otherwise nonempty polygon.
    [[[[0, 0], [1, 0], [0, 1], [0, 0]]]],  # MultiPolygon nesting in Polygon.
    [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]],  # Self-intersection.
    [
        [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
        [[3, 3], [4, 3], [4, 4], [3, 3]],  # Hole outside the shell.
    ],
])
def test_malformed_polygon_is_rejected(coordinates: object) -> None:
    feature = {"geometry": {"type": "Polygon", "coordinates": coordinates}}
    assert not _geometry_ok(feature, NEW_SUBDIVISIONS)


def test_valid_polygon_and_multipolygon_are_accepted() -> None:
    polygon = [[[-87, 34], [-86, 34], [-86, 35], [-87, 34]]]
    assert _geometry_ok(
        {"geometry": {"type": "Polygon", "coordinates": polygon}}, NEW_SUBDIVISIONS
    )
    assert _geometry_ok(
        {"geometry": {"type": "MultiPolygon", "coordinates": [polygon]}},
        NEW_SUBDIVISIONS,
    )


@pytest.mark.parametrize("bad_point", [
    [-181.0, 34.0], [-87.0, 91.0], [1200000.0, 500000.0], [10**400, 34],
])
def test_reviewed_scope_rejects_out_of_range_wgs84_coordinates(
    tmp_path: Path, bad_point: list[int | float]
) -> None:
    _scope(tmp_path)
    path = tmp_path / "reviewed-scope.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for geometry_name in ("boundary_geometry", "context_geometry"):
        polygon = payload[geometry_name]
        polygon["rings"][0][0] = bad_point
        polygon["rings"][0][-1] = bad_point
        payload[geometry_name.replace("geometry", "sha256")] = _digest(polygon)
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScopeError, match="invalid_scope_polygon"):
        ReviewedScope.load(path)


@pytest.mark.parametrize("bad_number", [b"NaN", b"Infinity", b"1e1000"])
def test_nonfinite_json_page_fails_closed_and_records_report(
    tmp_path: Path, bad_number: bytes
) -> None:
    page = (
        b'{"type":"FeatureCollection","features":[{"type":"Feature",'
        b'"properties":{"OBJECTID":1,"PermitID":1},"geometry":'
        b'{"type":"Point","coordinates":[' + bad_number + b',34.5]}}]}'
    )
    transport, _ = _fixture([1], raw_page=page)
    report = _run(tmp_path, transport)
    assert report["coverage"] == "failed"
    assert report["error_code"] == "nonfinite_json_number"
    assert (tmp_path / "stage" / "report.json").is_file()


def test_huge_integer_feature_coordinate_is_rejected_without_aborting(tmp_path: Path) -> None:
    feature = _feature(1)
    feature["geometry"] = {"type": "Point", "coordinates": [10**400, 34.5]}
    transport, _ = _fixture([1], batch_override=[feature])
    report = _run(tmp_path, transport)
    assert report["coverage"] == "partial"
    assert report["rejected"] == 1


def test_empty_scope_and_canary_are_distinct(tmp_path: Path) -> None:
    transport, _ = _fixture([])
    empty = _run(tmp_path, transport)
    assert empty["coverage"] == "complete" and empty["expected"] == 0
    transport, requests = _fixture(list(range(100)))
    canary = _run(tmp_path, transport, canary=True)
    assert canary["coverage"] == "unknown"
    assert canary["fetched"] == 25 and canary["requests"] == 4
    assert len(requests) == 4


def test_large_polygon_query_uses_form_post_under_same_request_budget(tmp_path: Path) -> None:
    _scope(tmp_path)
    scope_path = tmp_path / "reviewed-scope.json"
    payload = json.loads(scope_path.read_text(encoding="utf-8"))
    large_polygon = {
        "rings": [[[-87.0, 34.0], *[
            [-86.0, 34.0 + index / 100_000] for index in range(150)
        ], [-87.0, 34.0]]],
        "spatialReference": {"wkid": 4326},
    }
    payload["boundary_geometry"] = large_polygon
    payload["context_geometry"] = large_polygon
    payload["boundary_sha256"] = _digest(large_polygon)
    payload["context_sha256"] = _digest(large_polygon)
    scope_path.write_text(json.dumps(payload), encoding="utf-8")
    transport, requests = _fixture([1])
    with httpx.Client(transport=transport) as client:
        report = stage_scoped_source(
            CONFIG, ReviewedScope.load(scope_path), tmp_path / "large-canary", client=client,
            canary=True, budget=CollectionBudget(max_requests=4, max_attempts=1,
                                                min_interval_seconds=0),
        )
    assert report["coverage"] == "unknown" and report["requests"] == 4
    assert [request["__method"] for request in requests] == ["GET", "POST", "POST", "POST"]
    assert len({request["geometry"] for request in requests[1:]}) == 1
    assert [event["method"] for event in report["request_log"]] == [
        "GET", "POST", "POST", "POST"
    ]
    assert all(event["status"] == 200 and event["response_bytes"] > 0
               for event in report["request_log"])


def test_canary_stops_on_429_without_retry(tmp_path: Path) -> None:
    transport, requests = _fixture([1], transient=True)
    with httpx.Client(transport=transport) as client:
        report = stage_scoped_source(
            CONFIG, _scope(tmp_path), tmp_path / "rate-limited", client=client,
            canary=True,
            budget=CollectionBudget(max_requests=4, max_attempts=1,
                                    min_interval_seconds=0),
        )
    assert report["coverage"] == "failed" and report["requests"] == 2
    assert report["retries"] == 0 and len(requests) == 2
    assert [event["status"] for event in report["request_log"]] == [200, 429]


def test_429_retry_and_safety_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.ingestion.scoped_arcgis._retry_delay", lambda *_: 0)
    transport, _ = _fixture([1], transient=True)
    report = _run(tmp_path, transport)
    assert report["coverage"] == "complete" and report["retries"] == 1
    transport, _ = _fixture(list(range(101)))
    with httpx.Client(transport=transport) as client:
        capped = stage_scoped_source(
            CONFIG, _scope(tmp_path), tmp_path / "limited", client=client,
            budget=CollectionBudget(max_ids=100, min_interval_seconds=0),
        )
    assert capped["error_code"] == "id_budget_exceeded"
    assert capped["coverage"] == "partial"


def test_timeout_retry_and_metadata_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.ingestion.scoped_arcgis._retry_delay", lambda *_: 0)
    base, _ = _fixture([1])
    timed_out = False

    def timeout_once(request: httpx.Request) -> httpx.Response:
        nonlocal timed_out
        if "returnCountOnly=true" in str(request.url) and not timed_out:
            timed_out = True
            raise httpx.ReadTimeout("fixture timeout")
        return base.handle_request(request)

    retried = _run(tmp_path, httpx.MockTransport(timeout_once))
    assert retried["coverage"] == "complete" and retried["retries"] == 1

    def wrong_crs(request: httpx.Request) -> httpx.Response:
        response = base.handle_request(request)
        if str(request.url).split("?")[0].endswith("/0"):
            payload = response.json()
            payload["extent"]["spatialReference"]["wkid"] = 3857
            return httpx.Response(200, json=payload)
        return response

    drifted = _run(tmp_path, httpx.MockTransport(wrong_crs))
    assert drifted["coverage"] == "failed"
    assert drifted["error_code"] == "source_crs_drift"


def test_scope_digest_and_review_required(tmp_path: Path) -> None:
    _scope(tmp_path)
    path = tmp_path / "reviewed-scope.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["boundary_geometry"]["rings"][0][0][0] = -85.0
    payload["boundary_geometry"]["rings"][0][-1][0] = -85.0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScopeError, match="boundary_digest_mismatch"):
        ReviewedScope.load(path)
    payload["boundary_geometry"] = POLYGON
    payload["reviewed_at"] = None
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScopeError, match="scope_not_reviewed"):
        ReviewedScope.load(path)


def test_unsealed_or_incomplete_staging_cannot_mark_complete(tmp_path: Path) -> None:
    transport, _ = _fixture([1, 2])
    report = _run(tmp_path, transport)
    page_shas = {page["sha256"] for page in report["pages"]}
    scope = _scope(tmp_path)

    def verified_sha() -> str:
        return hashlib.sha256(
            json.dumps(report, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        ).hexdigest()

    with pytest.raises(ScopeError, match="report_digest_assertion_mismatch"):
        source_batch_from_staging(
            report, (), scope=scope, page_sha256_assertions=page_shas,
            report_sha256_assertion=None, run_id="run-1",
        )
    with pytest.raises(ScopeError, match="page_digest_assertions_mismatch"):
        source_batch_from_staging(
            report, (), scope=scope, page_sha256_assertions=set(),
            report_sha256_assertion=verified_sha(), run_id="run-1",
        )
    report["expected"] = 3
    with pytest.raises(ScopeError, match="complete_coverage_unproven"):
        source_batch_from_staging(
            report, (), scope=scope, page_sha256_assertions=page_shas,
            report_sha256_assertion=verified_sha(), run_id="run-1",
        )
    report["expected"] = 2
    report.pop("reconciliation")
    fake_records = tuple(SourceRecord(str(i), f"p{i}", {}, {}) for i in (1, 2))
    with pytest.raises(ScopeError, match="transport_reconciliation_missing"):
        source_batch_from_staging(
            report, fake_records, scope=scope, page_sha256_assertions=page_shas,
            report_sha256_assertion=verified_sha(), run_id="run-1",
        )
    report["coverage"] = "partial"
    batch = source_batch_from_staging(
        report, (), scope=scope, page_sha256_assertions=page_shas,
        report_sha256_assertion=verified_sha(), run_id="run-1",
    )
    assert batch.coverage == "partial"
    assert batch.quarantined_count == 2
    report["canary"] = True
    with pytest.raises(ScopeError, match="canary_cannot_publish"):
        source_batch_from_staging(
            report, (), scope=scope, page_sha256_assertions=page_shas,
            report_sha256_assertion=verified_sha(), run_id="run-1",
        )
    report["canary"] = False
    report["nonfinite"] = float("nan")
    with pytest.raises(ScopeError, match="invalid_staged_report"):
        source_batch_from_staging(
            report, (), scope=scope, page_sha256_assertions=page_shas,
            report_sha256_assertion=None, run_id="run-1",
        )


def test_offset_full_page_without_transfer_flag_and_repeated_page(tmp_path: Path) -> None:
    config = replace(CONFIG, connector_config={"pagination": "offset"})
    requests: list[dict[str, str]] = []
    replay = False

    def handler(request: httpx.Request) -> httpx.Response:
        params = {key: values[0] for key, values in parse_qs(request.url.query.decode()).items()}
        requests.append(params)
        if str(request.url).split("?")[0].endswith("/0"):
            return httpx.Response(200, json={
                "geometryType": "esriGeometryPoint", "supportedQueryFormats": "geoJSON",
                "extent": {"spatialReference": {"wkid": 102629}},
                "objectIdField": "OBJECTID",
                "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"},
                           {"name": "PermitID", "type": "esriFieldTypeInteger"}],
                "advancedQueryCapabilities": {
                    "supportsPagination": True, "supportsOrderBy": True,
                },
                "editingInfo": {"lastEditDate": 1234},
            })
        if params.get("returnCountOnly") == "true":
            return httpx.Response(200, json={"count": 251})
        offset = int(params["resultOffset"])
        values = [0] if replay and offset else range(offset, min(offset + 250, 251))
        # No exceededTransferLimit key: a full page must still advance.
        return httpx.Response(200, json={
            "type": "FeatureCollection", "features": [_feature(value) for value in values],
        })

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        complete = stage_scoped_source(
            config, _scope(tmp_path), tmp_path / "offset-ok", client=client,
            budget=CollectionBudget(min_interval_seconds=0),
        )
    assert complete["coverage"] == "complete" and complete["fetched"] == 251
    assert [r["resultOffset"] for r in requests if "resultOffset" in r] == ["0", "250"]
    replay = True
    with httpx.Client(transport=transport) as client:
        repeated = stage_scoped_source(
            config, _scope(tmp_path), tmp_path / "offset-replay", client=client,
            budget=CollectionBudget(min_interval_seconds=0),
        )
    assert repeated["coverage"] == "partial"
    assert repeated["error_code"] == "offset_page_repeated_or_empty"


def test_attempt_health_preserves_last_good_and_discloses_unactivated_scope(tmp_path: Path) -> None:
    transport, _ = _fixture([1])
    report = _run(tmp_path, transport)
    existing = {"status": "healthy", "sources": [{
        "key": CONFIG.key, "status": "healthy",
        "last_success_at": "2026-09-01T00:00:00Z", "records_created": 9,
    }], "records": {"published": 9}}
    updated = scoped_attempt_health(existing, report)
    row = updated["sources"][0]
    assert row["status"] == "staged"
    assert row["coverage"]["status"] == "unknown"
    assert row["latest_attempt"]["status"] == "complete"
    assert row["latest_attempt"]["publication_status"] == "not_activated"
    assert row["last_success_at"] == "2026-09-01T00:00:00Z"
    assert row["records_created"] == 9
    assert row["attempt_records_staged"] == 1
    assert updated["records"] == {"published": 9}
    assert _aggregate_status([row, {"status": "healthy", "error_count": 0}]) == "degraded"
