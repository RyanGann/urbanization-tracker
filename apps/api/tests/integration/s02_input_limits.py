"""Isolated HTTP/PostGIS S02 acceptance. No external sources or real mail."""

from __future__ import annotations

import argparse
import copy
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from pyproj import Geod
from sqlalchemy import select, text

from app.config import get_settings
from app.db import SessionLocal
from app.models import Phase3CollectionItem, ProcessedCollectionItem
from app.public_geometry import validate_public_geometry

POLYGON = {
    "type": "Polygon",
    "coordinates": [[[-86.7, 34.6], [-86.5, 34.6], [-86.5, 34.8], [-86.7, 34.8], [-86.7, 34.6]]],
}
PRIVATE = ["S02-private-contact@example.test", "S02-PRIVATE-NOTE", "S02-PRIVATE-TOKEN"]


def run(api: str, token: str, result: Path, phase: str) -> None:
    client = httpx.Client(base_url=api, timeout=20)
    reviewer = {"Authorization": f"Bearer {token}"}
    submission = {
        "title": "S02 located source tip",
        "notes": PRIVATE[1],
        "submitter_contact": PRIVATE[0],
        "source_url": "https://example.test/s02",
        "geometry": {"type": "Point", "coordinates": [-86.6, 34.7]},
    }
    watch = {"name": "S02 watch", "email": "s02-fixture@example.test", "geometry": POLYGON}

    def reset_quota() -> None:
        with SessionLocal.begin() as session:
            session.execute(text("DELETE FROM public_write_quotas"))

    def assert_private_absent(response: httpx.Response) -> None:
        assert all(sentinel not in response.text for sentinel in PRIVATE)

    if phase == "verify":
        for route, payload in [("public-submissions", submission), ("watch-areas", watch)]:
            response = client.post(f"/api/{route}", json=payload)
            assert response.status_code == 429, response.status_code
            assert int(response.headers["retry-after"]) > 0
        report = json.loads(result.read_text())
        report["quota_survived_restart"] = True
        result.write_text(json.dumps(report, indent=2))
        return

    assertions: list[str] = []
    reset_quota()
    oversized = client.post("/api/public-submissions", content=b"x" * (256 * 1024 + 1))
    assert oversized.status_code == 413
    # httpx iterator sends Transfer-Encoding: chunked, without Content-Length.
    chunked = client.post("/api/public-submissions", content=iter([b"x" * 200_000, b"y" * 100_000]))
    assert chunked.status_code == 413
    for body in [
        b"[" * 1000 + b"]" * 1000,
        ("[" * 1000 + "]" * 1000).encode("utf-16"),
        b'{"notes":"\xff"}',
    ]:
        response = client.post("/api/public-submissions", content=body)
        assert response.status_code == 422
        assert_private_absent(response)
    assertions.append("oversize_and_chunked_413_bounded_nested_and_encoded_json_422")

    malformed = [
        {**submission, "source_url": "javascript:alert(1)"},
        {**submission, "submitter_contact": "invalid@@example.test"},
        {**submission, "geometry": {"type": "Point", "coordinates": [10**400, 34]}},
        {**submission, "geometry": {"type": "Point", "coordinates": [True, 34]}},
        {**submission, "geometry": {"type": "Point", "coordinates": [0, 0, 1]}},
        {**submission, "geometry": {"type": "Point", "coordinates": [181, 34]}},
    ]
    for payload in malformed:
        reset_quota()
        response = client.post("/api/public-submissions", json=payload)
        assert response.status_code == 422, response.text
        assert_private_absent(response)
    reset_quota()
    nan_body = json.dumps(
        {**submission, "geometry": {"type": "Point", "coordinates": [float("nan"), 34]}}
    )
    assert (
        client.post(
            "/api/public-submissions",
            content=nan_body,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 422
    )
    for filters in [
        {"unknown": []},
        {"statuses": ["invented"]},
        {"development_types": "subdivision"},
    ]:
        reset_quota()
        assert (
            client.post("/api/watch-areas", json={**watch, "filters": filters}).status_code == 422
        )
    assertions.append("finite_2d_coordinates_urls_emails_and_shared_filter_allowlists")

    bowtie = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
    hole = [[-86.65, 34.65], [-86.55, 34.65], [-86.55, 34.75], [-86.65, 34.75], [-86.65, 34.65]]
    donut = {"type": "Polygon", "coordinates": [*POLYGON["coordinates"], hole]}
    outside_hole = {
        "type": "Polygon",
        "coordinates": [*POLYGON["coordinates"], [[0, 0], [0.1, 0], [0.1, 0.1], [0, 0.1], [0, 0]]],
    }
    multipart = {
        "type": "MultiPolygon",
        "coordinates": [
            donut["coordinates"],
            [[[-86.4, 34.6], [-86.3, 34.6], [-86.3, 34.7], [-86.4, 34.7], [-86.4, 34.6]]],
        ],
    }
    huge = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    cases = [(bowtie, 422), (outside_hole, 422), (donut, 200), (multipart, 200), (huge, 422)]
    # Bracket the real geodesic limit. Differences between backends must stay <1m².
    geod = Geod(ellps="WGS84")
    boundary_areas = []
    for target, expected in [(2499.0, 200), (2501.0, 422)]:
        low, high = 0.1, 1.0
        for _ in range(45):
            width = (low + high) / 2
            ring = [
                [-86.7, 34.6],
                [-86.7 + width, 34.6],
                [-86.7 + width, 35.05],
                [-86.7, 35.05],
                [-86.7, 34.6],
            ]
            area = abs(geod.polygon_area_perimeter(*zip(*ring, strict=True))[0])
            if area < target * 1_000_000:
                low = width
            else:
                high = width
        boundary = {"type": "Polygon", "coordinates": [ring]}
        with SessionLocal() as session:
            pg_area = float(
                session.execute(
                    text(
                        "SELECT ST_Area(ST_SetSRID(ST_GeomFromGeoJSON(:geometry),4326)::geography)"
                    ),
                    {"geometry": json.dumps(boundary)},
                ).scalar_one()
            )
        assert abs(pg_area - area) < 1.0
        boundary_areas.append({"target_sq_km": target, "postgis_sq_m": pg_area, "local_sq_m": area})
        cases.append((boundary, expected))
    for geometry, expected in cases:
        reset_quota()
        response = client.post("/api/watch-areas", json={**watch, "geometry": geometry})
        assert response.status_code == expected, response.text
        assert_private_absent(response)
        # The independent local mode must agree without reading any live canonical data.
        os.environ["DATA_MODE"] = "demo"
        get_settings.cache_clear()
        try:
            local = 200
            try:
                validate_public_geometry(geometry, watch=True)
            except HTTPException as exc:
                local = exc.status_code
            assert local == expected
        finally:
            os.environ["DATA_MODE"] = "live"
            get_settings.cache_clear()
    assertions.append("postgis_topology_holes_multipart_area_and_local_backend_parity")

    reset_quota()
    response = client.post("/api/public-submissions", json={**submission, "geometry": None})
    assert response.status_code == 200
    assert_private_absent(response)
    staged = next(
        row
        for row in client.get("/api/reviewer/staged-records", headers=reviewer).json()
        if row["source_payload"].get("submission_id") == response.json()["id"]
    )
    assert staged["geometry"] is None
    approval = client.post(
        f"/api/reviewer/staged-records/{staged['id']}/approve", json={}, headers=reviewer
    )
    assert approval.status_code == 409
    imported = client.post(
        "/api/reviewer/decisions/import",
        headers=reviewer,
        json={"decisions": [{"staged_id": staged["id"], "review_status": "approved"}]},
    )
    assert imported.status_code == 409
    assertions.append("unknown_location_null_staging_both_publication_paths_blocked")

    reset_quota()
    response = client.post("/api/public-submissions", json=submission)
    assert response.status_code == 200
    staged = next(
        row
        for row in client.get("/api/reviewer/staged-records", headers=reviewer).json()
        if row["source_payload"].get("submission_id") == response.json()["id"]
    )
    approval = client.post(
        f"/api/reviewer/staged-records/{staged['id']}/approve", json={}, headers=reviewer
    )
    assert approval.status_code == 200, approval.text
    assert_private_absent(approval)
    published_id = approval.json()["public_id"]
    # Poison internal arbitrary dictionaries to test legacy read boundaries too.
    with SessionLocal.begin() as session:
        for model, collection in [
            (ProcessedCollectionItem, "development_records"),
            (Phase3CollectionItem, "development_records"),
        ]:
            for row in session.scalars(select(model).where(model.collection_name == collection)):
                payload = copy.deepcopy(row.payload_json)
                payload["source_fields"].update(
                    {"contact": PRIVATE[0], "notes": PRIVATE[1], "token": PRIVATE[2]}
                )
                payload["private_notes"] = PRIVATE[1]
                row.payload_json = payload
        for row in session.scalars(
            select(Phase3CollectionItem).where(
                Phase3CollectionItem.collection_name == "record_versions"
            )
        ):
            payload = copy.deepcopy(row.payload_json)
            payload["snapshot"]["source_fields"]["token"] = PRIVATE[2]
            payload["snapshot"]["reviewer_private_notes"] = PRIVATE[1]
            row.payload_json = payload
    for path in [
        "/api/development-records",
        "/api/map/development-records.geojson",
        f"/api/development-records/{published_id}",
        f"/api/development-records/{published_id}/versions",
    ]:
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert_private_absent(response)
    assertions.append("private_contact_notes_tokens_absent_from_receipt_detail_map_history")

    reset_quota()
    quota_results = {}
    for route, payload in [("public-submissions", submission), ("watch-areas", watch)]:
        barrier = threading.Barrier(20)

        def attempt(
            index: int,
            barrier: threading.Barrier = barrier,
            route: str = route,
            payload: dict[str, Any] = payload,
        ) -> int:
            barrier.wait()
            with httpx.Client(base_url=api, timeout=30) as separate:
                response = separate.post(
                    f"/api/{route}",
                    json=payload,
                    headers={"X-Forwarded-For": f"198.51.100.{index + 1}"},
                )
                if response.status_code == 429:
                    assert int(response.headers["retry-after"]) > 0
                return response.status_code

        with ThreadPoolExecutor(max_workers=20) as pool:
            statuses = list(pool.map(attempt, range(20)))
        assert statuses.count(200) == 10 and statuses.count(429) == 10, statuses
        quota_results[route] = {"accepted": 10, "rejected": 10}
    with SessionLocal() as session:
        rows = session.execute(
            text("SELECT client_key, route, attempts FROM public_write_quotas")
        ).all()
        assert len(rows) == 2 and all(
            len(row.client_key) == 64 and row.attempts == 10 for row in rows
        )
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        postgis = session.execute(text("SELECT PostGIS_Full_Version()")).scalar_one()
    assertions.append("two_worker_concurrency_shared_budget_spoofed_forwarding_no_bypass")
    result.write_text(
        json.dumps(
            {
                "assertions": assertions,
                "quotas": quota_results,
                "schema_revision": revision,
                "postgis": postgis,
                "geodesic_boundary_areas": boundary_areas,
                "quota_survived_restart": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--reviewer-token", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--phase", choices=["create", "verify"], required=True)
    args = parser.parse_args()
    run(args.api_url, args.reviewer_token, args.result, args.phase)
