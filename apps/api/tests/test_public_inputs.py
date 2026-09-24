from __future__ import annotations

import asyncio
import json
from collections.abc import Generator
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import get_settings
from app.main import app
from app.public_body import MAX_PUBLIC_BODY_BYTES, PublicWriteBodyLimit
from app.public_geometry import validate_geometry_structure, validate_public_geometry
from app.public_quota import _local_counts, normalized_address, trusted_client_address
from app.seed_store import reset_seed_state

POLYGON = {
    "type": "Polygon",
    "coordinates": [[[-86.7, 34.6], [-86.5, 34.6], [-86.5, 34.8], [-86.7, 34.8], [-86.7, 34.6]]],
}


@pytest.fixture(autouse=True)
def demo(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    monkeypatch.setenv("DATA_MODE", "demo")
    get_settings.cache_clear()
    _local_counts.clear()
    reset_seed_state()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "coordinates",
    [
        [True, 34],
        [10**400, 34],
        [0, float("nan")],
        [0, float("inf")],
        [181, 34],
        [0, 91],
        [0, 0, 1],
        [[[0, 0]]],
    ],
)
def test_bad_coordinates(coordinates: Any) -> None:
    with pytest.raises(ValueError):
        validate_geometry_structure({"type": "Point", "coordinates": coordinates})


def test_holes_multipart_and_bowtie() -> None:
    hole = [[-86.65, 34.65], [-86.55, 34.65], [-86.55, 34.75], [-86.65, 34.75], [-86.65, 34.65]]
    donut = {"type": "Polygon", "coordinates": [*POLYGON["coordinates"], hole]}
    validate_public_geometry(donut, watch=True)
    validate_public_geometry(
        {"type": "MultiPolygon", "coordinates": [donut["coordinates"]]}, watch=True
    )
    bowtie = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
    with pytest.raises(HTTPException) as rejected:
        validate_public_geometry(bowtie, watch=True)
    assert rejected.value.status_code == 422


def test_geometry_budgets() -> None:
    for geometry in [
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},
        {"type": "Polygon", "coordinates": [[[179, 0], [-179, 0], [-179, 1], [179, 0]]]},
        {"type": "Polygon", "coordinates": [[[0, 0]] * 2001]},
    ]:
        with pytest.raises(ValueError):
            validate_geometry_structure(geometry)
    with pytest.raises(HTTPException):
        validate_public_geometry(
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
            watch=True,
        )


def test_unknown_location_and_safe_errors() -> None:
    client = TestClient(app)
    payload = {
        "title": "Unknown location",
        "notes": "PRIVATE-NOTE-SENTINEL",
        "submitter_contact": "private-contact@example.test",
    }
    response = client.post("/api/public-submissions", json=payload)
    assert response.status_code == 200
    assert "PRIVATE" not in response.text and "private-contact" not in response.text
    staged = next(
        item
        for item in client.get("/api/reviewer/staged-records").json()
        if item["source_payload"].get("submission_id") == response.json()["id"]
    )
    assert staged["geometry"] is None
    rejected = client.post(f"/api/reviewer/staged-records/{staged['id']}/approve", json={})
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "location_required"
    invalid = client.post(
        "/api/public-submissions", json={**payload, "source_url": "file:///secret"}
    )
    assert invalid.status_code == 422 and "PRIVATE" not in invalid.text
    assert "private-contact" not in invalid.text and "file:///secret" not in invalid.text


def test_json_nesting_and_encoding() -> None:
    client = TestClient(app)
    for body in [
        b"[" * 1000 + b"]" * 1000,
        ("[" * 1000 + "]" * 1000).encode("utf-16"),
        b'{"notes":"\xff"}',
    ]:
        response = client.post("/api/public-submissions", content=body)
        assert response.status_code == 422
        assert response.headers["cache-control"] == "no-store"


def test_chunked_or_lying_content_length_is_bounded_before_app() -> None:
    async def run() -> None:
        called = False

        async def downstream(scope: Any, receive: Any, send: Any) -> None:
            nonlocal called
            called = True

        chunks = iter(
            [
                {"type": "http.request", "body": b"x" * 200_000, "more_body": True},
                {"type": "http.request", "body": b"y" * 100_000, "more_body": False},
            ]
        )
        messages = []

        async def receive() -> Any:
            return next(chunks)

        async def send(message: Any) -> None:
            messages.append(message)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/public-submissions",
            "headers": [(b"content-length", b"1")],
        }
        await PublicWriteBodyLimit(downstream)(scope, receive, send)
        assert not called and messages[0]["status"] == 413

    asyncio.run(run())
    response = TestClient(app).post("/api/watch-areas", content=b"x" * (MAX_PUBLIC_BODY_BYTES + 1))
    assert response.status_code == 413


def test_filters_email_and_local_quota() -> None:
    client = TestClient(app)
    watch = {"name": "Valid watch", "email": "fixture@example.test", "geometry": POLYGON}
    for change in [
        {"email": "invalid@@example.test"},
        {"filters": {"private": []}},
        {"filters": {"statuses": ["invented"]}},
        {"geometry": {"type": "Point", "coordinates": [0, 0]}},
    ]:
        assert client.post("/api/watch-areas", json={**watch, **change}).status_code == 422
    for _ in range(6):
        assert (
            client.post("/api/watch-areas", json={**watch, "filters": {"statuses": []}}).status_code
            == 200
        )
    response = client.post("/api/watch-areas", json=watch)
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0


def test_proxy_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    def request(peer: str, forwarded: str) -> Request:
        return Request(
            {
                "type": "http",
                "client": (peer, 1),
                "headers": [(b"x-forwarded-for", forwarded.encode())],
            }
        )

    assert normalized_address("::ffff:192.0.2.1") == "192.0.2.1"
    with pytest.raises(ValueError):
        normalized_address("2001:db8::1%untrusted-zone")
    assert trusted_client_address(request("192.0.2.1", "198.51.100.1")) == "192.0.2.1"
    monkeypatch.setenv("PUBLIC_WRITE_TRUSTED_PROXIES", "10.0.0.0/8")
    get_settings.cache_clear()
    assert trusted_client_address(request("10.0.0.1", "198.51.100.1, 10.0.0.2")) == "198.51.100.1"
    assert trusted_client_address(request("10.0.0.1", "198.51.100.1, broken")) == "10.0.0.1"
    assert trusted_client_address(request("10.0.0.1", "broken, 198.51.100.1")) == "198.51.100.1"


def test_public_fields_allowlist_and_history() -> None:
    from app.schemas import DevelopmentRecord, RecordVersion

    record = TestClient(app).get("/api/development-records").json()["records"][0]
    record["source_fields"].update(
        {
            "contact": "PRIVATE-CONTACT",
            "token": "PRIVATE-TOKEN",
            "notes": "PRIVATE-NOTES",
            "SubdID": "safe-source-id",
        }
    )
    record["private_notes"] = "PRIVATE-TOP-LEVEL"
    record["geometry"]["private_notes"] = "PRIVATE-GEOMETRY"
    public = DevelopmentRecord.model_validate(record).model_dump()
    version = RecordVersion(
        id="test",
        public_id=record["public_id"],
        version_number=1,
        changed_at="2026-09-22",
        changed_by="reviewer",
        change_type="published",
        snapshot=record,
    ).model_dump()
    assert "PRIVATE" not in json.dumps([public, version])
    assert public["source_fields"]["SubdID"] == "safe-source-id"


def test_live_missing_quota_secret_fails_closed_only_public_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATA_MODE", "live")
    monkeypatch.setenv("PHASE3_STORE_BACKEND", "postgres")
    monkeypatch.delenv("PUBLIC_WRITE_QUOTA_SECRET", raising=False)
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.post(
        "/api/public-submissions", json={"title": "Valid title", "notes": "Valid private notes"}
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "write_quota_unavailable"
    assert client.get("/health").status_code == 200


def test_corrupt_history_fails_with_safe_availability_error() -> None:
    from app.data_availability import DataUnavailableError
    from app.schemas import RecordVersion

    with pytest.raises(DataUnavailableError) as caught:
        RecordVersion(
            id="test",
            public_id="record",
            version_number=1,
            changed_at="2026-09-22",
            changed_by="reviewer",
            change_type="published",
            snapshot={"contact": "PRIVATE-CONTACT"},
        )
    assert "PRIVATE" not in str(caught.value)


def test_rejection_logs_only_aggregate_reason(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="uvicorn.error"):
        response = TestClient(app).post("/api/watch-areas", json={"email": "PRIVATE-CONTACT"})
    assert response.status_code == 422
    assert "public_write_rejected reason=invalid_request" in caplog.text
    assert "PRIVATE-CONTACT" not in caplog.text
