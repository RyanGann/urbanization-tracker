import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.config import Settings, get_settings
from app.ingestion.artifact_config import require_hosted_artifact_storage
from app.ingestion.artifact_sink import ArtifactError
from app.ingestion import agenda_pipeline
from app.schemas import PublicSourceHealth, SourceDocument


def test_hosted_ingestion_fails_closed_on_local_artifact_sink() -> None:
    settings = Settings(
        hosted_ingestion_enabled=True,
        artifact_durability_required=True,
        artifact_sink="local",
    )
    with pytest.raises(ArtifactError, match="artifact_configuration"):
        require_hosted_artifact_storage(settings)
    require_hosted_artifact_storage(
        settings.model_copy(update={"artifact_sink": "s3"})
    )


def test_public_provenance_omits_internal_locators_and_signed_queries() -> None:
    private = "PRIVATE_SIGNED_TOKEN"
    health = PublicSourceHealth.model_validate(
        {
            "status": "degraded",
            "raw_artifact": f"s3://private-bucket/{private}",
            "sources": [
                {
                    "key": "example",
                    "source_url": f"https://example.test/layer?token={private}",
                    "raw_artifact": f"C:/private/{private}",
                    "validation_errors": [f"upload failed at {private}"],
                    "metadata": {"signed_url": f"https://example.test/?secret={private}"},
                }
            ],
        }
    ).model_dump_json()
    document = SourceDocument.model_validate(
        {
            "id": "doc",
            "title": "Agenda",
            "url": f"https://example.test/agenda.pdf?signature={private}",
            "storage_uri": f"s3://private-bucket/{private}",
            "extracted_text_uri": f"file:///private/{private}",
            "extraction_status": "complete",
        }
    ).model_dump_json()
    assert private not in health + document
    health_data = json.loads(health)
    document_data = json.loads(document)
    assert "raw_artifact" not in health_data
    assert "raw_artifact" not in health_data["sources"][0]
    assert "storage_uri" not in document_data
    assert "https://example.test/agenda.pdf" in document


def test_agenda_parser_failure_preserves_existing_revision_in_durable_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARTIFACT_DURABILITY_REQUIRED", "true")
    get_settings.cache_clear()
    replaced: list[object] = []
    private = "PRIVATE_SIGNED_TOKEN"

    class FakeArtifactService:
        sink_id = "local-test"

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def upload_file(self, **_kwargs: object) -> UUID:
            return uuid4()

        def cleanup_verified(self, _reference_id: UUID, _path: Path) -> None:
            pass

    def parse_document(
        **kwargs: Any,
    ) -> tuple[dict[str, object], list[dict[str, str]], tuple[UUID, UUID]]:
        if kwargs["title"] == "bad":
            raise RuntimeError(f"failed at https://example.test/?signature={private}")
        return (
            {"id": "new", "parsed_item_count": 1},
            [{"id": "new-item", "title": "New Item"}],
            (uuid4(), uuid4()),
        )

    monkeypatch.setattr(agenda_pipeline, "ArtifactService", FakeArtifactService)
    monkeypatch.setattr(agenda_pipeline, "_fetch_archive_html", lambda _client: ("html", "test"))
    monkeypatch.setattr(
        agenda_pipeline,
        "discover_agenda_links",
        lambda *_args, **_kwargs: [
            SimpleNamespace(title="good", url="https://example.test/good.pdf"),
            SimpleNamespace(title="bad", url="https://example.test/bad.pdf"),
        ],
    )
    monkeypatch.setattr(agenda_pipeline, "_fetch_and_parse_document", parse_document)
    monkeypatch.setattr(
        agenda_pipeline, "replace_agenda_artifacts", lambda **kwargs: replaced.append(kwargs)
    )
    try:
        with httpx.Client() as client:
            health = agenda_pipeline.ingest_huntsville_agendas(
                data_dir=tmp_path, client=client, document_limit=2
            )
    finally:
        get_settings.cache_clear()

    assert replaced == []
    assert health["status"] == "degraded"
    assert health["validation_errors"] == ["agenda_source_error"]
    assert private not in str(health)
