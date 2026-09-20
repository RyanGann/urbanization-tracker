import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.phase3_store import reset_phase3_state

client = TestClient(app)


def configure_live_artifacts(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("DATA_MODE", "live")
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "artifact")
    monkeypatch.setenv("PHASE3_STORE_BACKEND", "artifact")
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    reset_phase3_state(force_memory=False)
    return tmp_path / "processed"


def test_live_missing_canonical_collection_is_503_without_demo_fallback(monkeypatch, tmp_path) -> None:
    configure_live_artifacts(monkeypatch, tmp_path)

    status = client.get("/api/dataset-status")
    records = client.get("/api/development-records")
    detail = client.get("/api/development-records/hsv-westmoore-landing-ph1")
    geojson = client.get("/api/map/development-records.geojson")

    assert status.json()["availability"] == "uninitialized"
    for response in (records, detail, geojson):
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "data_unavailable"
        assert "westmoore" not in response.text.lower()


def test_live_initialized_empty_collection_is_empty_and_unknown_detail_is_404(monkeypatch, tmp_path) -> None:
    processed = configure_live_artifacts(monkeypatch, tmp_path)
    processed.mkdir()
    (processed / "development_records.json").write_text("[]", encoding="utf-8")
    (processed / "environmental_overlays.json").write_text("[]", encoding="utf-8")

    status = client.get("/api/dataset-status")
    records = client.get("/api/development-records")
    detail = client.get("/api/development-records/unknown-record")
    geojson = client.get("/api/map/development-records.geojson")

    assert status.json() == {
        "data_mode": "live",
        "availability": "ready",
        "dataset_revision": None,
        "source_freshness": None,
        "declared_scope": None,
    }
    assert records.status_code == 200
    assert records.json() == {"data_mode": "live", "records": []}
    assert detail.status_code == 404
    assert geojson.json()["features"] == []
    assert geojson.json()["data_mode"] == "live"


def test_live_corrupt_canonical_collection_is_503(monkeypatch, tmp_path) -> None:
    processed = configure_live_artifacts(monkeypatch, tmp_path)
    processed.mkdir()
    (processed / "development_records.json").write_text("{not-json", encoding="utf-8")

    response = client.get("/api/development-records")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "data_unavailable"


def test_demo_is_explicit_and_labelled(monkeypatch) -> None:
    monkeypatch.setenv("DATA_MODE", "demo")
    get_settings.cache_clear()

    status = client.get("/api/dataset-status")
    records = client.get("/api/development-records")

    assert status.json()["data_mode"] == "demo"
    assert status.json()["availability"] == "ready"
    assert records.json()["data_mode"] == "demo"
    assert records.json()["records"]
