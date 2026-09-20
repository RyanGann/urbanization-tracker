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


def test_live_missing_canonical_collection_is_503_without_demo_fallback(
    monkeypatch, tmp_path
) -> None:
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


def test_live_initialized_empty_collection_is_empty_and_unknown_detail_is_404(
    monkeypatch, tmp_path
) -> None:
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


def test_live_invalid_record_schema_is_unavailable_in_status_and_reads(
    monkeypatch, tmp_path
) -> None:
    processed = configure_live_artifacts(monkeypatch, tmp_path)
    processed.mkdir()
    (processed / "development_records.json").write_text("[{}]", encoding="utf-8")

    status = client.get("/api/dataset-status")
    records = client.get("/api/development-records")

    assert status.json()["availability"] == "unavailable"
    assert records.status_code == 503
    assert records.json()["detail"]["code"] == "data_unavailable"


def test_live_missing_staged_collection_is_503(monkeypatch, tmp_path) -> None:
    configure_live_artifacts(monkeypatch, tmp_path)

    response = client.get("/api/reviewer/staged-records")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "data_unavailable"


def test_live_missing_source_health_is_503(monkeypatch, tmp_path) -> None:
    configure_live_artifacts(monkeypatch, tmp_path)

    response = client.get("/api/source-health")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "data_unavailable"


def test_demo_catalog_initialization_preserves_direct_phase3_submission(monkeypatch) -> None:
    monkeypatch.setenv("DATA_MODE", "demo")
    get_settings.cache_clear()
    monkeypatch.setattr("app.seed_store._active_data_mode", None)
    reset_phase3_state(force_memory=False)

    created = client.post(
        "/api/public-submissions",
        json={
            "title": "Direct demo submission",
            "source_url": "https://example.test/direct-demo",
            "notes": "Created before the demo catalog is read.",
            "submitter_contact": "demo@example.test",
        },
    )
    assert created.status_code == 200

    catalog = client.get("/api/development-records")
    submissions = client.get("/api/reviewer/public-submissions")

    assert catalog.status_code == 200
    assert submissions.status_code == 200
    assert any(row["title"] == "Direct demo submission" for row in submissions.json())
