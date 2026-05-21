from pathlib import Path
from typing import Any

from app.config import get_settings
from app.ingestion import pipeline
from app.processed_store import (
    processed_store_status,
    read_processed_list,
    read_processed_payload,
    write_processed_list,
    write_processed_payload,
)


def teardown_function() -> None:
    get_settings.cache_clear()


def test_processed_store_reads_and_writes_artifact_lists(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "artifact")
    get_settings.cache_clear()

    write_processed_list(
        "development_records",
        [{"public_id": "hsv-test", "title": "Stored record"}],
    )
    write_processed_payload(
        "source_health",
        {"status": "healthy", "sources": [], "records": {"published": 1}},
    )

    assert read_processed_list("development_records") == [
        {"public_id": "hsv-test", "title": "Stored record"}
    ]
    assert read_processed_payload("source_health") == {
        "status": "healthy",
        "sources": [],
        "records": {"published": 1},
    }

    status = processed_store_status()
    collections = {collection["name"]: collection for collection in status["collections"]}
    assert status["backend"] == "artifact"
    assert status["database_first"] is False
    assert collections["development_records"]["artifact_count"] == 1
    assert collections["source_health"]["artifact_count"] == 1


def test_processed_store_status_flags_unmigrated_artifacts(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "artifact")
    get_settings.cache_clear()
    write_processed_list("development_records", [{"public_id": "hsv-unmigrated"}])

    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "postgres")
    get_settings.cache_clear()

    def empty_postgres_counts() -> tuple[dict[str, int], str | None]:
        return {}, None

    monkeypatch.setattr("app.processed_store._postgres_collection_counts", empty_postgres_counts)

    status = processed_store_status()
    collections = {collection["name"]: collection for collection in status["collections"]}

    assert status["backend"] == "postgres"
    assert status["database_first"] is True
    assert collections["development_records"]["artifact_count"] == 1
    assert collections["development_records"]["database_count"] == 0
    assert collections["development_records"]["requires_migration"] is True


def test_ingestion_writes_canonical_processed_collections_to_postgres_backend(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "postgres")
    get_settings.cache_clear()
    stored: dict[str, list[dict[str, Any]]] = {}

    def read_items(name: str) -> list[dict[str, Any]]:
        return stored.get(name, [])

    def write_items(name: str, items: list[dict[str, Any]]) -> None:
        stored[name] = items

    monkeypatch.setattr("app.processed_store._read_postgres_items", read_items)
    monkeypatch.setattr("app.processed_store._write_postgres_items", write_items)

    health = pipeline._write_processed_state(
        data_dir=Path(tmp_path),
        run_id="test-run",
        checked_at="2026-05-21T00:00:00+00:00",
        source_health=[
            {
                "key": "huntsville_new_subdivisions",
                "name": "Huntsville New Subdivisions",
                "source_url": "https://example.test/layer",
                "status": "healthy",
                "checked_at": "2026-05-21T00:00:00+00:00",
                "records_seen": 1,
                "records_created": 1,
                "error_count": 0,
            }
        ],
        raw_records=[
            {
                "data_source_key": "huntsville_new_subdivisions",
                "source_record_id": "1",
                "payload_json": {},
                "fetched_at": "2026-05-21T00:00:00+00:00",
                "payload_sha256": "abc",
            }
        ],
        staged_records=[
            {
                "id": "stage-hsv-test",
                "source_url": "https://example.test/layer",
            }
        ],
        published_records=[
            {
                "public_id": "hsv-test",
                "source_url": "https://example.test/layer",
                "proximity_flags": [],
            }
        ],
        overlays=[],
    )

    assert health["records"]["published"] == 1
    assert stored["development_records"][0]["public_id"] == "hsv-test"
    assert stored["staged_development_records"][0]["id"] == "stage-hsv-test"
    assert stored["source_health"][0]["run_id"] == "test-run"
    assert not (tmp_path / "processed" / "development_records.json").exists()
    assert (tmp_path / "processed" / "raw_records.json").exists()
