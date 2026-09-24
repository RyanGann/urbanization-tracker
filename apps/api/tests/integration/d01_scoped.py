"""D01's real PostGIS/API source-attempt and restart scenario, using local ArcGIS HTTP."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from app.db import SessionLocal
from app.ingestion.scoped_arcgis import (
    CollectionBudget,
    ReviewedScope,
    _digest,
    record_scoped_attempts,
    stage_scoped_source,
)
from app.ingestion.sources.huntsville import BUILDING_PERMITS
from app.transactional_store import CollectionUnitOfWork

SOURCE_KEY = BUILDING_PERMITS.key
LAST_SUCCESS = "2026-09-01T00:00:00Z"
SCOPE_POLYGON = {
    "rings": [[[-86.6, 34.4], [-86.4, 34.4], [-86.4, 34.6], [-86.6, 34.4]]],
    "spatialReference": {"wkid": 4326},
}


def _hash_records() -> str:
    with SessionLocal() as session:
        rows = CollectionUnitOfWork(session).list_processed("development_records")
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _public_health(api_url: str) -> dict[str, object]:
    with urlopen(f"{api_url}/api/source-health", timeout=10) as response:  # noqa: S310
        if response.status != 200:
            raise AssertionError(f"source-health API returned {response.status}")
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise AssertionError("source-health API did not return an object")
    return payload


def _source_row(payload: dict[str, object]) -> dict[str, object]:
    rows = payload.get("sources")
    if not isinstance(rows, list):
        raise AssertionError("source-health rows missing")
    row = next((item for item in rows if isinstance(item, dict)
                and item.get("key") == SOURCE_KEY), None)
    if row is None:
        raise AssertionError("D01 source-health row missing")
    return row


class FixtureHandler(BaseHTTPRequestHandler):
    mode = "complete"
    request_count = 0

    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def _handle(self) -> None:
        type(self).request_count += 1
        url = urlsplit(self.path)
        encoded = (self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
                   if self.command == "POST" else url.query)
        params = {key: values[0] for key, values in parse_qs(encoded).items()}
        if url.path.endswith("/0"):
            payload: dict[str, object] = {
                "geometryType": "esriGeometryPoint",
                "supportedQueryFormats": "JSON, geoJSON",
                "extent": {"spatialReference": {"wkid": 102629}},
                "objectIdField": "OBJECTID",
                "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"},
                           {"name": "PermitID", "type": "esriFieldTypeInteger"}],
            }
        elif params.get("returnCountOnly") == "true":
            payload = {"count": 2}
        elif params.get("returnIdsOnly") == "true":
            payload = {"objectIdFieldName": "OBJECTID", "objectIds":
                       [1, 2] if type(self).mode == "complete" else [1]}
        elif "objectIds" in params:
            ids = [int(value) for value in params["objectIds"].split(",")]
            payload = {"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {"OBJECTID": value, "PermitID": value},
                 "geometry": {"type": "Point", "coordinates": [-86.5, 34.5]}}
                for value in ids
            ]}
        else:
            payload = {"error": {"code": 400, "message": "unexpected fixture query"}}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _scope_file(directory: Path) -> Path:
    payload = {
        "version": "huntsville-city-limits-layer0-repaired-guard10-v1",
        "boundary_source_url": (
            "https://maps.huntsvilleal.gov/server/rest/services/"
            "Boundaries/CityLimits/MapServer/0"
        ),
        "boundary_where": "CityName = 'Huntsville'",
        "source_srid": 102629,
        "raw_boundary_response_sha256": "0" * 64,
        "boundary_algorithm": "ArcGIS-rings-ST_MakeValid-linework-v1",
        "boundary_geometry": SCOPE_POLYGON,
        "boundary_sha256": _digest(SCOPE_POLYGON),
        "context_geometry": SCOPE_POLYGON,
        "context_sha256": _digest(SCOPE_POLYGON),
        "context_buffer_m": 510,
        "context_algorithm": "EPSG:5070-buffer-510m-for-500m-screening-v1",
        "reviewed_at": "2026-09-23T00:00:00Z",
    }
    path = directory / "synthetic-scope.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def stage(api_url: str, result_path: Path) -> None:
    before_records = _hash_records()
    existing = {"status": "healthy", "sources": [{
        "key": SOURCE_KEY, "status": "healthy", "checked_at": LAST_SUCCESS,
        "last_success_at": LAST_SUCCESS, "records_created": 9,
        "coverage": {"status": "complete"},
    }], "records": {"published": 9}}
    with SessionLocal.begin() as session:
        unit = CollectionUnitOfWork(session)
        with unit.canonical_mutation():
            unit.upsert_processed("source_health", "latest", existing)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        scope = ReviewedScope.load(_scope_file(root))
        server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            from dataclasses import replace

            config = replace(BUILDING_PERMITS,
                             service_url=f"http://127.0.0.1:{server.server_port}",
                             out_fields=("PermitID",), max_records=None)
            budget = CollectionBudget(max_requests=10, max_attempts=1,
                                      min_interval_seconds=0)
            FixtureHandler.mode = "complete"
            complete = stage_scoped_source(config, scope, root / "complete", budget=budget)
            if (complete["coverage"], complete["expected"], complete["accepted"]) != (
                "complete", 2, 2
            ):
                raise AssertionError(f"local HTTP complete page failed: {complete!r}")
            record_scoped_attempts([complete])
            staged = _source_row(_public_health(api_url))
            if (staged["status"] != "staged"
                or staged["latest_attempt"]["status"] != "complete"
                or staged["coverage"] != {"status": "complete"}):
                raise AssertionError(f"staged public health incorrect: {staged!r}")
            FixtureHandler.mode = "mismatch"
            failed = stage_scoped_source(config, scope, root / "mismatch", budget=budget)
            if failed["coverage"] != "failed" or failed.get("error_code") != (
                "count_id_mismatch"
            ) or failed["expected"] != 2 or failed["fetched"] != 0:
                raise AssertionError(f"mismatch did not fail closed: {failed!r}")
            record_scoped_attempts([failed])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    after = _public_health(api_url)
    row = _source_row(after)
    if (row["status"] != "failing" or row["latest_attempt"]["status"] != "failed"
        or row["latest_attempt"]["publication_status"] != "not_activated"
        or row["coverage"] != {"status": "complete"}
        or row["last_success_at"] != LAST_SUCCESS or row["records_created"] != 9
        or after.get("records") != {"published": 9}
        or _hash_records() != before_records):
        raise AssertionError(f"failed attempt displaced last-good data: {row!r}")
    result = {"fixture_http_requests": FixtureHandler.request_count,
              "complete_requests": complete["requests"],
              "failed_requests": failed["requests"],
              "before_development_sha256": before_records,
              "after_development_sha256": _hash_records(),
              "source_row": row, "source_health_status": after["status"]}
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")


def verify(api_url: str, result_path: Path) -> None:
    expected = json.loads(result_path.read_text(encoding="utf-8"))
    payload = _public_health(api_url)
    row = _source_row(payload)
    if row != expected["source_row"] or payload["status"] != expected["source_health_status"]:
        raise AssertionError("source attempt health changed after API restart")
    if _hash_records() != expected["before_development_sha256"]:
        raise AssertionError("canonical development rows changed after API restart")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--phase", choices=("stage", "verify"), required=True)
    args = parser.parse_args()
    if args.phase == "stage":
        stage(args.api_url, args.result)
    else:
        verify(args.api_url, args.result)
    print(json.dumps({"phase": args.phase, "status": "pass", "result": str(args.result)}))


if __name__ == "__main__":
    main()
