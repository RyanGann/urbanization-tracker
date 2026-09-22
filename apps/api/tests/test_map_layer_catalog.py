from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.map_layer_catalog import build_catalog, catalog_revision, merge_ingestion_catalog
from app.processed_store import write_processed_payload

client = TestClient(app)


def test_ingestion_catalog_merge_preserves_ready_delivery_and_extension_metadata() -> None:
    layer = {
        "id": "wetlands",
        "kind": "vector",
        "title": "Wetlands",
        "category": "context",
        "data_version": "old",
        "display_version": "tiles-v1",
        "delivery_status": "ready",
        "tile_url": "https://tiles.example/v1",
        "source_layer": "wetlands",
        "minzoom": 1,
        "maxzoom": 14,
        "bounds": [-87.0, 34.0, -86.0, 35.0],
        "coverage": {
            "status": "unknown",
            "scope_id": None,
            "reported_count": 1,
            "fetched_count": 1,
        },
        "source_name": "Agency",
        "source_url": "https://source.example",
        "attribution": "Agency",
        "caveat": "",
        "data_as_of": None,
        "fetched_at": "2026-09-20T00:00:00+00:00",
        "default_visible": True,
    }
    existing = {
        "data_mode": "live",
        "catalog_revision": "",
        "layers": [layer],
        "imports": {"future": "preserved"},
    }
    existing["catalog_revision"] = catalog_revision({"data_mode": "live", "layers": [layer]})
    incoming_layer = {**layer, "data_version": "new", "delivery_status": "failed", "tile_url": None}
    incoming = {"data_mode": "live", "catalog_revision": "", "layers": [incoming_layer]}
    incoming["catalog_revision"] = catalog_revision(
        {"data_mode": "live", "layers": [incoming_layer]}
    )

    merged = merge_ingestion_catalog(existing, incoming)

    assert merged["layers"] == [layer]
    assert merged["imports"] == {"future": "preserved"}


@pytest.fixture(autouse=True)
def clear_settings() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_demo_catalog_is_compact_cached_and_does_not_read_legacy_overlays(monkeypatch) -> None:
    monkeypatch.setenv("DATA_MODE", "demo")
    monkeypatch.setattr(
        "app.seed_store.list_environmental_overlays",
        lambda: (_ for _ in ()).throw(AssertionError("legacy overlay reader was called")),
    )

    response = client.get("/api/map/layers")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60, must-revalidate"
    expected_etag = '"104117014a4ace26bc81701db43af0ded517e151740dce857b2f57bf3f35567e"'
    assert response.headers["etag"] == expected_etag
    assert len(response.content) <= 50 * 1024
    body = response.json()
    assert body["data_mode"] == "demo"
    assert {layer["id"] for layer in body["layers"]} == {
        "pilot-boundary",
        "wetlands",
        "floodplain",
        "hydrography",
        "parks-open-space",
    }
    assert all("features" not in layer and "coordinates" not in layer for layer in body["layers"])

    not_modified = client.get(
        "/api/map/layers", headers={"If-None-Match": response.headers["etag"]}
    )
    assert not_modified.status_code == 304
    assert not_modified.content == b""


def test_live_catalog_is_persisted_and_mode_matched(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATA_MODE", "live")
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "artifact")
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    payload = {
        "data_mode": "live",
        "catalog_revision": "",
        "layers": [],
    }
    payload["catalog_revision"] = catalog_revision({"data_mode": "live", "layers": []})
    write_processed_payload("map_layer_catalog", payload)

    response = client.get("/api/map/layers")

    assert response.status_code == 200
    assert response.json() == payload

    write_processed_payload("map_layer_catalog", {**payload, "catalog_revision": "0" * 64})
    mismatched = client.get("/api/map/layers")
    assert mismatched.status_code == 503
    assert mismatched.headers["cache-control"] == "no-store"


def test_live_catalog_rejects_a_valid_catalog_from_the_other_mode(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATA_MODE", "live")
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "artifact")
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    payload = {
        "data_mode": "demo",
        "catalog_revision": catalog_revision({"data_mode": "demo", "layers": []}),
        "layers": [],
    }
    write_processed_payload("map_layer_catalog", payload)

    response = client.get("/api/map/layers")

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"


def test_catalog_etag_changes_with_validated_metadata(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATA_MODE", "live")
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "artifact")
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    class Source:
        key = "etag-layer"
        name = "ETag layer"
        category = "wetlands"
        source_agency = "Agency"
        layer_url = "https://example.test/etag-layer"
        attribution = "Agency"
        caveat = "Context only"
        default_visible = True

    initial = build_catalog([(Source(), {"status": "healthy", "records_seen": 1})])
    write_processed_payload("map_layer_catalog", initial)
    initial_response = client.get("/api/map/layers")
    changed = build_catalog([(Source(), {"status": "healthy", "records_seen": 2})])
    write_processed_payload("map_layer_catalog", changed)
    changed_response = client.get("/api/map/layers")

    assert initial_response.status_code == 200
    assert changed_response.status_code == 200
    assert initial_response.headers["etag"] != changed_response.headers["etag"]


def test_populated_live_catalog_is_compact_and_never_reads_legacy_bulk(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("DATA_MODE", "live")
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "artifact")
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    class Source:
        key = "live-layer"
        name = "Live layer"
        category = "wetlands"
        source_agency = "Agency"
        layer_url = "https://example.test/live-layer"
        attribution = "Agency"
        caveat = "Context only"
        default_visible = True

    payload = build_catalog([(Source(), {"status": "healthy", "records_seen": 1, "metadata": {}})])
    write_processed_payload("map_layer_catalog", payload)
    monkeypatch.setattr(
        "app.map_layer_catalog.read_processed_list_result",
        lambda _collection: (_ for _ in ()).throw(
            AssertionError("legacy overlay reader was called")
        ),
    )

    response = client.get("/api/map/layers")

    assert response.status_code == 200
    assert len(response.content) <= 50 * 1024
    assert response.json()["layers"][0]["id"] == "live-layer"
    assert "features" not in response.text and "coordinates" not in response.text


def test_missing_live_catalog_is_unavailable_and_not_cacheable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATA_MODE", "live")
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "artifact")
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    response = client.get("/api/map/layers")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "data_unavailable"
    assert response.headers["cache-control"] == "no-store"


def test_catalog_builder_uses_source_metadata_without_geometry() -> None:
    class Source:
        key = "layer-a"
        name = "Layer A"
        category = "wetlands"
        source_agency = "Agency"
        layer_url = "https://example.test/layer"
        attribution = "Agency"
        caveat = "Context only"
        default_visible = True

    catalog = build_catalog(
        [
            (
                Source(),
                {
                    "status": "healthy",
                    "checked_at": "2026-09-20T00:00:00Z",
                    "records_seen": 2,
                    "raw_artifact_sha256": "abc",
                    "metadata": {"reported_count": 3},
                },
            )
        ]
    )

    encoded = json.dumps(catalog).encode()
    assert len(encoded) <= 50 * 1024
    assert catalog["layers"][0]["id"] == "layer-a"
    assert catalog["layers"][0]["delivery_status"] == "processing"
    assert catalog["layers"][0]["coverage"]["reported_count"] == 3


def test_catalog_coverage_only_marks_observed_truncation_partial() -> None:
    class Source:
        key = "coverage-layer"
        name = "Coverage layer"
        category = "wetlands"
        source_agency = "Agency"
        layer_url = "https://example.test/coverage-layer"
        attribution = "Agency"
        caveat = "Context only"
        default_visible = True

    equal_counts = build_catalog(
        [
            (
                Source(),
                {
                    "status": "healthy",
                    "records_seen": 2_000,
                    "metadata": {"reported_count": 2_000},
                },
            )
        ]
    )
    truncated = build_catalog(
        [
            (
                Source(),
                {
                    "status": "healthy",
                    "records_seen": 2_000,
                    "metadata": {"reported_count": 2_001},
                },
            )
        ]
    )
    failed = build_catalog([(Source(), {"status": "failed", "records_seen": 0})])

    assert equal_counts["layers"][0]["coverage"]["status"] == "unknown"
    assert truncated["layers"][0]["coverage"]["status"] == "partial"
    assert failed["layers"][0]["coverage"]["status"] == "failed"


def test_catalog_builder_keeps_the_two_real_huntsville_layer_ids() -> None:
    from app.ingestion.sources.huntsville import FEMA_FLOODPLAIN_1PCT, USFWS_WETLANDS

    catalog = build_catalog(
        [
            (FEMA_FLOODPLAIN_1PCT, {"status": "healthy", "records_seen": 4_000}),
            (USFWS_WETLANDS, {"status": "healthy", "records_seen": 4_000}),
        ]
    )

    assert [layer["id"] for layer in catalog["layers"]] == [
        "huntsville_fema_1pct_floodplain",
        "huntsville_usfws_wetlands",
    ]
    assert all(layer["delivery_status"] == "processing" for layer in catalog["layers"])
    assert len(json.dumps(catalog).encode()) <= 50 * 1024


def test_offline_backfill_is_the_only_path_that_projects_bulk_overlay_metadata(
    monkeypatch, tmp_path
) -> None:
    from app.map_layer_catalog import backfill_map_layer_catalog
    from app.processed_store import read_processed_payload, write_processed_list

    monkeypatch.setenv("DATA_MODE", "live")
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "artifact")
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    write_processed_list(
        "environmental_overlays",
        [
            {
                "id": "offline-layer",
                "name": "Offline layer",
                "category": "wetlands",
                "source_url": "https://example.test/layer",
                "attribution": "Example",
                "caveat": "Context only",
                "geom_type": "polygon",
                "features": {
                    "type": "FeatureCollection",
                    "features": [{"geometry": {"type": "Point", "coordinates": [1, 2]}}],
                },
            }
        ],
    )

    catalog = backfill_map_layer_catalog()

    assert catalog.layers[0].id == "offline-layer"
    assert catalog.layers[0].coverage.fetched_count == 1
    persisted = read_processed_payload("map_layer_catalog")
    assert persisted is not None
    assert "coordinates" not in json.dumps(persisted)


def test_malformed_live_catalog_is_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATA_MODE", "live")
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "artifact")
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    payload = {"data_mode": "live", "catalog_revision": "0" * 64, "layers": [{}]}
    write_processed_payload("map_layer_catalog", payload)

    response = client.get("/api/map/layers")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "data_unavailable"


def test_release_upgrade_preserves_catalog_and_missing_source_state(monkeypatch, tmp_path) -> None:
    from app.map_layer_catalog import upgrade_map_layer_catalog
    from app.processed_store import write_processed_list

    monkeypatch.setenv("DATA_MODE", "live")
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "artifact")
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    assert upgrade_map_layer_catalog() == {"status": "uninitialized"}
    assert client.get("/api/map/layers").status_code == 503

    write_processed_list("environmental_overlays", [])
    assert upgrade_map_layer_catalog() == {"status": "created"}
    catalog_path = tmp_path / "processed" / "map_layer_catalog.json"
    before = catalog_path.read_bytes()
    monkeypatch.setattr(
        "app.map_layer_catalog.read_processed_list_result",
        lambda _collection: (_ for _ in ()).throw(AssertionError("unnecessary legacy read")),
    )
    assert upgrade_map_layer_catalog() == {"status": "preserved"}
    assert catalog_path.read_bytes() == before

    catalog_path.write_text("{}", encoding="utf-8")
    from app.data_availability import DataUnavailableError

    with pytest.raises(DataUnavailableError):
        upgrade_map_layer_catalog()
    assert catalog_path.read_text(encoding="utf-8") == "{}"
