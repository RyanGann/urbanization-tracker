from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from app.config import get_settings
from app.ingestion.artifact_service import ArtifactService
from app.ingestion.artifact_sink import ArtifactError, BlobIdentity, hash_stream
from app.ingestion.artifacts import write_staged_bytes
from app.ingestion.connectors.arcgis import ArcGISLayerConfig, ArcGISRestConnector
from app.ingestion.pipeline import _fetch_source
from app.ingestion.sources.huntsville import NEW_SUBDIVISIONS


def test_staging_budget_allows_boundary_and_rejects_before_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARTIFACT_DURABILITY_REQUIRED", "true")
    monkeypatch.setenv("ARTIFACT_STAGING_MAX_BYTES", "4")
    get_settings.cache_clear()
    try:
        first = tmp_path / "raw" / "first.bin"
        second = tmp_path / "processed" / "source_documents" / "second.txt"
        write_staged_bytes(tmp_path, first, b"1234")
        assert first.read_bytes() == b"1234"
        with pytest.raises(ArtifactError, match="artifact_too_large"):
            write_staged_bytes(tmp_path, second, b"x")
        assert not second.exists()
        assert list(first.parent.glob(".first.bin.*")) == []
    finally:
        get_settings.cache_clear()


def test_cleanup_requires_verified_matching_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings().model_copy(
        update={
            "data_mode": "live",
            "processed_store_backend": "postgres",
            "ingestion_data_dir": tmp_path,
        }
    )
    service = ArtifactService.__new__(ArtifactService)
    service.settings = settings
    service.sink_id = "test-sink"
    path = tmp_path / "raw" / "sample.bin"
    path.parent.mkdir()
    path.write_bytes(b"verified")
    expected = BlobIdentity(hashlib.sha256(b"verified").hexdigest(), 8)
    reference_id = uuid4()
    state = "pending"

    def lookup(_reference_id: object, _sink_id: object) -> tuple[BlobIdentity, str]:
        return expected, state

    service.manifest = SimpleNamespace(lookup=lookup)  # type: ignore[assignment]
    with pytest.raises(ArtifactError, match="artifact_unavailable"):
        service.cleanup_verified(reference_id, path)
    assert path.exists()
    state = "verified"
    path.write_bytes(b"modified")
    with pytest.raises(ArtifactError, match="artifact_integrity"):
        service.cleanup_verified(reference_id, path)
    assert path.exists()
    path.write_bytes(b"verified")
    service.cleanup_verified(reference_id, path)
    assert not path.exists()


def test_concurrent_staging_writers_share_one_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARTIFACT_DURABILITY_REQUIRED", "true")
    monkeypatch.setenv("ARTIFACT_STAGING_MAX_BYTES", "4")
    get_settings.cache_clear()
    try:
        def stage(index: int) -> str:
            try:
                write_staged_bytes(tmp_path, tmp_path / "raw" / f"{index}.bin", b"123")
                return "written"
            except ArtifactError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(stage, (1, 2)))
        assert sorted(outcomes) == ["artifact_too_large", "written"]
        assert sum(path.stat().st_size for path in (tmp_path / "raw").iterdir()) == 3
    finally:
        get_settings.cache_clear()


def test_cleanup_cannot_unlink_a_concurrent_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARTIFACT_DURABILITY_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        settings = get_settings().model_copy(
            update={
                "data_mode": "live",
                "processed_store_backend": "postgres",
                "ingestion_data_dir": tmp_path,
            }
        )
        service = ArtifactService.__new__(ArtifactService)
        service.settings = settings
        service.sink_id = "test-sink"
        path = tmp_path / "raw" / "shared.bin"
        write_staged_bytes(tmp_path, path, b"verified")
        blob = BlobIdentity(hashlib.sha256(b"verified").hexdigest(), 8)
        service.manifest = SimpleNamespace(  # type: ignore[assignment]
            lookup=lambda _reference_id, _sink_id: (blob, "verified")
        )
        hashed = Event()
        release = Event()
        writer_started = Event()

        def pause_after_hash(source: Any, *, max_bytes: int) -> BlobIdentity:
            result = hash_stream(source, max_bytes=max_bytes)
            hashed.set()
            assert release.wait(timeout=5)
            return result

        def replace() -> None:
            writer_started.set()
            write_staged_bytes(tmp_path, path, b"new")

        monkeypatch.setattr("app.ingestion.artifact_service.hash_stream", pause_after_hash)
        with ThreadPoolExecutor(max_workers=2) as workers:
            cleanup = workers.submit(service.cleanup_verified, uuid4(), path)
            assert hashed.wait(timeout=5)
            writer = workers.submit(replace)
            assert writer_started.wait(timeout=5)
            with pytest.raises(FuturesTimeoutError):
                writer.result(timeout=0.1)
            release.set()
            cleanup.result(timeout=5)
            writer.result(timeout=5)
        assert path.read_bytes() == b"new"
    finally:
        get_settings.cache_clear()


def test_source_staging_limit_blocks_raw_write_before_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings().model_copy(
        update={"artifact_durability_required": True, "artifact_staging_max_bytes": 1}
    )

    class SyntheticConnector:
        def get_layer_metadata(self, _config: ArcGISLayerConfig) -> dict[str, Any]:
            return {}

        def get_count(self, _config: ArcGISLayerConfig) -> int:
            return 0

        def fetch_geojson(self, _config: ArcGISLayerConfig) -> dict[str, Any]:
            return {"type": "FeatureCollection", "features": []}

    def unexpected_upload(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("upload was called after staging budget rejection")

    monkeypatch.setattr("app.ingestion.artifacts.get_settings", lambda: settings)
    monkeypatch.setattr("app.ingestion.pipeline.get_settings", lambda: settings)
    monkeypatch.setattr(ArtifactService, "upload_file", unexpected_upload)
    result = _fetch_source(
        cast(ArcGISRestConnector, SyntheticConnector()),
        NEW_SUBDIVISIONS,
        tmp_path,
        "run-1",
        "2026-09-24T00:00:00+00:00",
    )
    assert result["health"]["_artifact_pending"] is True
    assert result["health"]["validation_errors"] == ["artifact_too_large"]
    assert not (tmp_path / "raw" / NEW_SUBDIVISIONS.key / "run-1.geojson").exists()
