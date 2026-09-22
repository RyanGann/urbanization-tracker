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
