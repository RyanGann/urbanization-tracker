from typing import Any

from app.config import get_settings
from app.phase3_store import (
    create_public_submission,
    phase3_store_status,
    reset_phase3_state,
)


def teardown_function() -> None:
    reset_phase3_state(force_memory=True)
    get_settings.cache_clear()


def test_phase3_store_status_reports_artifact_counts(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PHASE3_STORE_BACKEND", "artifact")
    get_settings.cache_clear()
    reset_phase3_state(force_memory=False)

    create_public_submission(
        {
            "title": "Status Test Submission",
            "source_url": "https://example.test/status",
            "notes": "Creates an artifact-backed public submission for store status.",
            "submitter_contact": "neighbor@example.test",
        },
        published_records=[],
    )

    status = phase3_store_status()
    collections = {collection["name"]: collection for collection in status["collections"]}

    assert status["backend"] == "artifact"
    assert status["database_first"] is False
    assert collections["public_submissions"]["artifact_count"] == 1
    assert collections["submission_staged_records"]["artifact_count"] == 1
    assert collections["public_submissions"]["requires_migration"] is False


def test_phase3_store_status_flags_unmigrated_artifacts(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PHASE3_STORE_BACKEND", "artifact")
    get_settings.cache_clear()
    reset_phase3_state(force_memory=False)
    create_public_submission(
        {
            "title": "Unmigrated Submission",
            "source_url": "https://example.test/unmigrated",
            "notes": "Leaves an artifact to flag before switching to database mode.",
            "submitter_contact": "neighbor@example.test",
        },
        published_records=[],
    )

    monkeypatch.setenv("PHASE3_STORE_BACKEND", "postgres")
    get_settings.cache_clear()

    def empty_postgres_counts() -> tuple[dict[str, int], str | None]:
        return {}, None

    monkeypatch.setattr("app.phase3_store._postgres_collection_counts", empty_postgres_counts)

    status: dict[str, Any] = phase3_store_status()
    collections = {collection["name"]: collection for collection in status["collections"]}

    assert status["backend"] == "postgres"
    assert status["database_first"] is True
    assert collections["public_submissions"]["artifact_count"] == 1
    assert collections["public_submissions"]["database_count"] == 0
    assert collections["public_submissions"]["requires_migration"] is True


def test_phase3_store_status_queries_database_counts_in_artifact_mode(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PHASE3_STORE_BACKEND", "artifact")
    get_settings.cache_clear()
    reset_phase3_state(force_memory=False)

    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "phase3_public_submissions.json").write_text(
        '[{"id":"one"}, {"id":"two"}]',
        encoding="utf-8",
    )

    def postgres_counts() -> tuple[dict[str, int], str | None]:
        return {"public_submissions": 1}, None

    monkeypatch.setattr("app.phase3_store._postgres_collection_counts", postgres_counts)

    status: dict[str, Any] = phase3_store_status()
    collections = {collection["name"]: collection for collection in status["collections"]}

    assert status["backend"] == "artifact"
    assert collections["public_submissions"]["database_count"] == 1
    assert collections["public_submissions"]["requires_migration"] is True


def test_phase3_store_status_reports_invalid_artifact_without_crashing(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PHASE3_STORE_BACKEND", "artifact")
    get_settings.cache_clear()
    reset_phase3_state(force_memory=False)

    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "phase3_public_submissions.json").write_text(
        '[{"id":"broken"}',
        encoding="utf-8",
    )

    def postgres_counts() -> tuple[dict[str, int], str | None]:
        return {}, None

    monkeypatch.setattr("app.phase3_store._postgres_collection_counts", postgres_counts)

    status: dict[str, Any] = phase3_store_status()
    collections = {collection["name"]: collection for collection in status["collections"]}

    assert collections["public_submissions"]["artifact_count"] == 0
    assert collections["public_submissions"]["artifact_error"].startswith("Invalid JSON")
    assert collections["public_submissions"]["requires_migration"] is False


def test_phase3_store_status_returns_relative_artifact_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PHASE3_STORE_BACKEND", "artifact")
    get_settings.cache_clear()
    reset_phase3_state(force_memory=False)

    def postgres_counts() -> tuple[dict[str, int], str | None]:
        return {}, None

    monkeypatch.setattr("app.phase3_store._postgres_collection_counts", postgres_counts)

    status: dict[str, Any] = phase3_store_status()
    collections = {collection["name"]: collection for collection in status["collections"]}

    assert status["raw_artifact_root"] == "raw"
    assert (
        collections["public_submissions"]["artifact_path"]
        == "processed/phase3_public_submissions.json"
    )
    assert not collections["public_submissions"]["artifact_path"].startswith(str(tmp_path))
