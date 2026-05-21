from pathlib import Path

from app.config import get_settings
from app.ingestion.artifacts import list_artifact_manifest, record_artifact


def test_record_artifact_tracks_storage_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACT_STORAGE_BASE_URI", "s3://urbanization-artifacts/alpha")
    get_settings.cache_clear()
    try:
        artifact_path = tmp_path / "raw" / "source" / "sample.geojson"
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")

        entry = record_artifact(
            data_dir=tmp_path,
            path=artifact_path,
            artifact_type="raw_geojson",
            source_key="sample_source",
            run_id="run-1",
            source_url="https://example.test/layer/0",
            content_type="application/geo+json",
        )
    finally:
        monkeypatch.delenv("ARTIFACT_STORAGE_BASE_URI", raising=False)
        get_settings.cache_clear()

    manifest = list_artifact_manifest(tmp_path)

    assert entry["storage_uri"] == "s3://urbanization-artifacts/alpha/raw/source/sample.geojson"
    assert entry["local_path"] == "raw/source/sample.geojson"
    assert entry["byte_size"] > 0
    assert len(entry["sha256"]) == 64
    assert manifest == [entry]
