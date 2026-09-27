from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from app.ingestion import cli
from app.ingestion.control_artifacts import ControlArtifactError, ControlArtifacts
from app.ingestion.pipeline import _aggregate_status
from app.ingestion.scoped_arcgis import (
    CollectionBudget,
    ReviewedScope,
    ScopeError,
    _digest,
    _geometry_ok,
    _Session,
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
CONTEXT_POLYGON = {
    "rings": [[[-88.0, 33.0], [-85.0, 33.0], [-85.0, 36.0], [-88.0, 36.0], [-88.0, 33.0]]],
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
                "context_geometry": CONTEXT_POLYGON,
                "context_sha256": _digest(CONTEXT_POLYGON),
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


def test_control_bodies_preserve_original_bytes_and_query_identity(tmp_path: Path) -> None:
    base, _ = _fixture([1])
    bodies: list[bytes] = []
    queries: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        response = base.handle_request(request)
        params = dict(request.url.params)
        if "objectIds" in params:
            return response
        # Whitespace, key order and Unicode must survive without reserialization.
        raw = b" \n" + response.content[:-1] + b', "private_note":"caf\xc3\xa9"}\n '
        bodies.append(raw)
        queries.append(params)
        return httpx.Response(200, content=raw)

    report = _run(tmp_path, httpx.MockTransport(handler))
    assert report["coverage"] == "complete"
    controls = report["control_artifacts"]
    assert [item["role"] for item in controls] == [
        "initial_metadata", "initial_count", "initial_ids", "final_ids"
    ]
    for index, item in enumerate(controls):
        retained = (tmp_path / "stage" / item["path"]).read_bytes()
        assert retained == bodies[index]
        assert item["sha256"] == hashlib.sha256(retained).hexdigest()
        assert item["bytes"] == len(retained)
        assert item["query_sha256"] == _digest(queries[index])
        assert item["source_key"] == CONFIG.key and item["run_id"] == report["run_id"]
        assert item["scope_id"] == report["scope_id"] and item["sequence"] == index
        assert item["status"] == 200
    assert "private_note" not in json.dumps(report)
    assert not list((tmp_path / "stage").glob("*.part"))


def test_control_evidence_is_observation_specific_and_canary_stays_bounded(tmp_path: Path) -> None:
    transport, requests = _fixture([1])
    first = _run(tmp_path, transport)
    original = {
        item["path"]: (tmp_path / "stage" / item["path"]).read_bytes()
        for item in first["control_artifacts"]
    }
    second = _run(tmp_path, transport, canary=True)
    assert first["run_id"] != second["run_id"]
    assert second["coverage"] == "unknown" and second["requests"] == 4
    assert len(requests) == 9
    assert [item["role"] for item in second["control_artifacts"]] == [
        "initial_metadata", "initial_count", "initial_ids"
    ]
    assert all((tmp_path / "stage" / name).read_bytes() == body
               for name, body in original.items())


def test_changed_ids_retain_both_original_controls_without_complete_claim(tmp_path: Path) -> None:
    transport, _ = _fixture([1], second_ids=[2])
    report = _run(tmp_path, transport)
    assert report["error_code"] == "upstream_ids_changed"
    controls = {item["role"]: item for item in report["control_artifacts"]}
    for role, expected_ids in (("initial_ids", [1]), ("final_ids", [2])):
        body = (tmp_path / "stage" / controls[role]["path"]).read_bytes()
        assert json.loads(body)["objectIds"] == expected_ids


@pytest.mark.parametrize("failure", ["timeout", "oversized", "deadline"])
def test_partial_control_body_is_never_finalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    clock = [0.0]
    monkeypatch.setattr("app.ingestion.scoped_arcgis.time.monotonic", lambda: clock[0])

    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b'{"count":'
            if failure == "timeout":
                raise httpx.ReadTimeout("private fixture diagnostic")
            if failure == "deadline":
                clock[0] = 100.0
            yield b" " * 100

    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, stream=Interrupted())
    )) as client:
        report = stage_scoped_source(
            CONFIG, _scope(tmp_path), tmp_path / "interrupted", client=client,
            budget=CollectionBudget(max_attempts=1,
                                    max_response_bytes=1000 if failure == "deadline" else 50,
                                    max_seconds=10, min_interval_seconds=0),
        )
    assert report["coverage"] != "complete"
    assert report["error_code"] == {
        "timeout": "transport_failure", "oversized": "response_byte_budget_exceeded",
        "deadline": "time_budget_exceeded",
    }[failure]
    assert report["control_artifacts"] == []
    assert not list((tmp_path / "interrupted").glob("control-*"))
    assert not list((tmp_path / "interrupted").glob("*.part"))
    assert "private fixture diagnostic" not in json.dumps(report)


def test_invalid_control_json_keeps_completed_original_diagnostic(tmp_path: Path) -> None:
    raw = b"<upstream-error>private detail</upstream-error>"
    report = _run(tmp_path, httpx.MockTransport(lambda _: httpx.Response(200, content=raw)))
    assert report["error_code"] == "invalid_json_response"
    assert report["coverage"] == "failed"
    assert len(report["control_artifacts"]) == 1
    item = report["control_artifacts"][0]
    assert (tmp_path / "stage" / item["path"]).read_bytes() == raw
    assert "private detail" not in json.dumps(report)


@pytest.mark.parametrize(("constant", "error"), [
    ("MAX_CONTROL_BYTES", "control_byte_budget_exceeded"),
    ("MAX_CONTROL_DESCRIPTOR_BYTES", "control_descriptor_budget_exceeded"),
    ("MAX_CONTROL_ARTIFACTS", "control_artifact_budget_exceeded"),
])
def test_control_caps_refuse_incomplete_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, constant: str, error: str,
) -> None:
    monkeypatch.setattr(f"app.ingestion.control_artifacts.{constant}", 0)
    transport, _ = _fixture([1])
    report = _run(tmp_path, transport)
    assert report["error_code"] == error
    assert report["coverage"] != "complete" and report["control_artifacts"] == []
    assert not list((tmp_path / "stage").glob("*.part"))


def test_control_roles_and_source_binding_reject_substitution(tmp_path: Path) -> None:
    recorder = ControlArtifacts(tmp_path, {
        "run_id": "00000000-0000-0000-0000-000000000001", "source_key": CONFIG.key,
    }, metadata_url=CONFIG.layer_url, query_url=CONFIG.query_url,
        expected_queries={"initial_metadata": "0" * 64})
    event = {"url": CONFIG.layer_url, "operation": "metadata", "method": "GET",
             "query_sha256": "0" * 64, "status": 200}
    for role, changed in (("../../unsafe", event), ("initial_count", event),
                          ("initial_metadata", {**event, "url": "https://other.invalid"}),
                          ("initial_metadata", {**event, "query_sha256": "1" * 64})):
        with pytest.raises(ControlArtifactError):
            with recorder.capture(role, changed):
                pytest.fail("invalid identity opened a file")
    with recorder.capture("initial_metadata", event) as body:
        body.write(b"{}")
    with pytest.raises(ControlArtifactError, match="control_role_repeated"):
        with recorder.capture("initial_metadata", event):
            pytest.fail("duplicate role opened a file")
    with pytest.raises(ControlArtifactError, match="control_run_invalid"):
        ControlArtifacts(tmp_path, {"run_id": "../unsafe"},
                         metadata_url=CONFIG.layer_url, query_url=CONFIG.query_url,
                         expected_queries={})


def test_control_writer_enforces_own_byte_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ingestion.control_artifacts.MAX_CONTROL_BYTES", 3)
    recorder = ControlArtifacts(tmp_path, {
        "run_id": "00000000-0000-0000-0000-000000000001", "source_key": CONFIG.key,
    }, metadata_url=CONFIG.layer_url, query_url=CONFIG.query_url,
        expected_queries={"initial_metadata": "0" * 64})
    event = {"url": CONFIG.layer_url, "operation": "metadata", "method": "GET",
             "query_sha256": "0" * 64, "status": 200}
    with pytest.raises(ControlArtifactError, match="control_byte_budget_exceeded"):
        with recorder.capture("initial_metadata", event) as body:
            body.write(b"{}")
            body.write(b"{}")
    assert recorder.descriptors == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("substitution", [{"geometry": "{}"}, {"time": "0,1"}])
def test_same_endpoint_operation_wrong_scope_query_refuses_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, substitution: dict[str, str],
) -> None:
    original = _Session.get

    def changed(self: _Session, url: str, params: dict[str, str],
                **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("control_role") == "initial_count":
            params = {**params, **substitution}
        return original(self, url, params, **kwargs)

    monkeypatch.setattr(_Session, "get", changed)
    transport, _ = _fixture([1])
    report = _run(tmp_path, transport)
    assert report["coverage"] == "failed"
    assert report["error_code"] == "control_role_query_mismatch"
    assert [item["role"] for item in report["control_artifacts"]] == ["initial_metadata"]


def test_page_cap_refuses_additional_geometry_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.ingestion.scoped_arcgis.MAX_PAGE_ARTIFACTS", 1)
    transport, _ = _fixture(list(range(501)))
    report = _run(tmp_path, transport)
    assert report["error_code"] == "page_artifact_budget_exceeded"
    assert report["coverage"] == "partial" and len(report["pages"]) == 1


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


@pytest.mark.parametrize("rings", [
    [[[0, 0], [0, 0], [0, 0], [0, 0]]],
    [[[0, 0], [2, 2], [0, 2], [2, 0], [0, 0]]],
    [
        [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
        [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]],
    ],
])
def test_reviewed_scope_rejects_degenerate_or_invalid_topology(
    tmp_path: Path, rings: list[list[list[int]]]
) -> None:
    _scope(tmp_path)
    path = tmp_path / "reviewed-scope.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["boundary_geometry"]["rings"] = rings
    payload["boundary_sha256"] = _digest(payload["boundary_geometry"])
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScopeError, match="invalid_scope_polygon"):
        ReviewedScope.load(path)


def test_reviewed_scope_accepts_nested_hole_and_island(tmp_path: Path) -> None:
    _scope(tmp_path)
    path = tmp_path / "reviewed-scope.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["boundary_geometry"]["rings"] = [
        [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
        [[1, 1], [1, 3], [3, 3], [3, 1], [1, 1]],
        [[1.4, 1.4], [2, 1.4], [1.4, 2], [1.4, 1.4]],
    ]
    payload["boundary_sha256"] = _digest(payload["boundary_geometry"])
    payload["context_geometry"] = {
        "rings": [[[-1, -1], [5, -1], [5, 5], [-1, 5], [-1, -1]]],
        "spatialReference": {"wkid": 4326},
    }
    payload["context_sha256"] = _digest(payload["context_geometry"])
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert ReviewedScope.load(path).boundary_sha256 == payload["boundary_sha256"]


@pytest.mark.parametrize("context", [
    POLYGON,  # Coincident boundary, without a context margin.
    {"rings": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
     "spatialReference": {"wkid": 4326}},  # Disjoint.
    {"rings": [[[-87, 34], [-86.5, 34], [-86.5, 34.5], [-87, 34]]],
     "spatialReference": {"wkid": 4326}},  # Strictly smaller.
])
def test_reviewed_context_must_cover_full_boundary_with_margin(
    tmp_path: Path, context: dict[str, object]
) -> None:
    _scope(tmp_path)
    path = tmp_path / "reviewed-scope.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["context_geometry"] = context
    payload["context_sha256"] = _digest(context)
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScopeError, match="context_does_not_cover_boundary"):
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


@pytest.mark.parametrize(("container_type", "feature_type", "error"), [
    (None, "Feature", "geojson_collection_type_invalid"),
    ("Other", "Feature", "geojson_collection_type_invalid"),
    ("FeatureCollection", None, "geojson_feature_type_invalid"),
    ("FeatureCollection", "Other", "geojson_feature_type_invalid"),
])
def test_non_geojson_pages_fail_before_staging(
    tmp_path: Path, container_type: str | None, feature_type: str | None,
    error: str,
) -> None:
    feature = _feature(1)
    if feature_type is None:
        feature.pop("type")
    else:
        feature["type"] = feature_type
    page: dict[str, object] = {"features": [feature]}
    if container_type is not None:
        page["type"] = container_type
    transport, _ = _fixture([1], raw_page=json.dumps(page).encode())
    report = _run(tmp_path, transport)
    assert report["coverage"] == "failed"
    assert report["error_code"] == error
    assert not list((tmp_path / "stage").glob("page-*.geojson"))


def test_huge_integer_feature_coordinate_is_rejected_without_aborting(tmp_path: Path) -> None:
    feature = _feature(1)
    feature["geometry"] = {"type": "Point", "coordinates": [10**400, 34.5]}
    transport, _ = _fixture([1], batch_override=[feature])
    report = _run(tmp_path, transport)
    assert report["coverage"] == "partial"
    assert report["rejected"] == 1


@pytest.mark.parametrize("coordinates", [
    ["-86.5", "34.5"], [True, 34.5], [-86.5, False],
])
def test_nonnumeric_geojson_point_is_rejected(
    tmp_path: Path, coordinates: list[object]
) -> None:
    feature = _feature(1)
    feature["geometry"] = {"type": "Point", "coordinates": coordinates}
    transport, _ = _fixture([1], batch_override=[feature])
    report = _run(tmp_path, transport)
    assert report["coverage"] == "partial"
    assert (report["accepted"], report["rejected"]) == (0, 1)


@pytest.mark.parametrize("geometry", [
    {"type": "Polygon", "coordinates": [[[-87, 34], ["-86", 34],
                                         [-86, 35], [-87, 34]]]},
    {"type": "MultiPolygon", "coordinates": [[[[-87, 34], [-86, True],
                                               [-86, 35], [-87, 34]]]]},
])
def test_nonnumeric_geojson_polygon_is_rejected(geometry: dict[str, object]) -> None:
    assert not _geometry_ok({"geometry": geometry}, NEW_SUBDIVISIONS)


def test_empty_scope_and_canary_are_distinct(tmp_path: Path) -> None:
    transport, _ = _fixture([])
    empty = _run(tmp_path, transport)
    assert empty["coverage"] == "complete" and empty["expected"] == 0
    transport, requests = _fixture(list(range(100)))
    canary = _run(tmp_path, transport, canary=True)
    assert canary["coverage"] == "unknown"
    assert canary["fetched"] == 25 and canary["requests"] == 4
    assert len(requests) == 4


def test_rejected_canary_sample_fails_closed(tmp_path: Path) -> None:
    feature = _feature(1)
    feature["properties"] = {"OBJECTID": 1}
    transport, _ = _fixture([1], batch_override=[feature])
    report = _run(tmp_path, transport, canary=True)
    assert report["coverage"] == "unknown"
    assert report["rejected"] == 1
    assert report["error_code"] == "sample_feature_rejected"


def test_canary_cli_rejects_sample_and_deduplicates_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(tmp_path)
    calls: list[str] = []

    def stage(config: object, *_args: object, **_kwargs: object) -> dict[str, object]:
        calls.append(CONFIG.key)
        return {"coverage": "unknown", "rejected": 1}

    monkeypatch.setattr(cli, "stage_scoped_source", stage)
    monkeypatch.setattr(sys, "argv", [
        "ingestion", "stage-scoped-arcgis", "--scope-file",
        str(tmp_path / "reviewed-scope.json"), "--output-dir", str(tmp_path / "stage"),
        "--canary", *[arg for _ in range(6) for arg in ("--source", CONFIG.key)],
    ])
    with pytest.raises(SystemExit, match="1"):
        cli.main()
    assert scope.reviewed_at and calls == [CONFIG.key]
    monkeypatch.setattr(cli, "stage_scoped_source", lambda *_args, **_kwargs: {
        "coverage": "unknown", "rejected": 0,
    })
    cli.main()  # Unknown coverage is normal for a clean, bounded canary.


def test_canary_cli_global_request_cap_precedes_any_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scope(tmp_path)
    monkeypatch.setattr(cli, "SOURCE_CONFIGS", {
        f"source-{index}": CONFIG for index in range(6)
    })
    calls: list[str] = []
    monkeypatch.setattr(cli, "stage_scoped_source", lambda *_args, **_kwargs: calls.append("x"))
    monkeypatch.setattr(sys, "argv", [
        "ingestion", "stage-scoped-arcgis", "--scope-file",
        str(tmp_path / "reviewed-scope.json"), "--output-dir", str(tmp_path / "stage"),
        "--canary", *[
            arg for index in range(6) for arg in ("--source", f"source-{index}")
        ],
    ])
    with pytest.raises(SystemExit, match="2"):
        cli.main()
    assert calls == []


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
    payload["context_geometry"] = CONTEXT_POLYGON
    payload["boundary_sha256"] = _digest(large_polygon)
    payload["context_sha256"] = _digest(CONTEXT_POLYGON)
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
    controls = complete["control_artifacts"]
    assert [item["role"] for item in controls] == [
        "initial_metadata", "initial_count", "final_count", "final_metadata"
    ]
    for role in ("initial_metadata", "final_metadata"):
        item = next(item for item in controls if item["role"] == role)
        assert json.loads((tmp_path / "offset-ok" / item["path"]).read_bytes())[
            "editingInfo"
        ]["lastEditDate"] == 1234
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
