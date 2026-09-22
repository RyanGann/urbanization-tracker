from pathlib import Path

import pytest

from app.ingestion.pipeline import ArtifactIdentityIngestionUnsupported, ingest_madison_county


def test_madison_county_artifact_ingestion_requires_postgres_identity_store(tmp_path: Path) -> None:
    """Source ingestion cannot mutate artifact snapshots after C03 identity support."""
    with pytest.raises(
        ArtifactIdentityIngestionUnsupported,
        match="cannot preserve C03 source identities",
    ):
        ingest_madison_county(data_dir=tmp_path, record_limit=1)


def test_source_ingestion_rejects_demo_mode_before_creating_a_connector(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATA_MODE", "demo")
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "postgres")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(
            ArtifactIdentityIngestionUnsupported, match="cannot preserve C03 source identities"
        ):
            ingest_madison_county(data_dir=tmp_path, record_limit=1)
    finally:
        get_settings.cache_clear()
