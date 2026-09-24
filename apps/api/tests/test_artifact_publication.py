import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.ingestion import agenda_pipeline
from app.ingestion.artifact_config import require_hosted_artifact_storage
from app.ingestion.artifact_sink import ArtifactError
from app.main import app
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
                    "coverage": {"status": "complete", "private_locator": private},
                    "latest_attempt": {
                        "status": "failed",
                        "publication_status": "not_activated",
                        "scope_id": "city-scope-v1:" + "a" * 64,
                        "scope_version": "city-scope-v1",
                        "boundary_sha256": "b" * 64,
                        "expected": 2,
                        "fetched": 0,
                        "accepted": 0,
                        "rejected": 0,
                        "signed_url": f"https://example.test/?secret={private}",
                    },
                    "last_success_at": "2026-09-23T00:00:00Z",
                    "error_code": "count_id_mismatch",
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
    assert health_data["sources"][0]["coverage"] == {"status": "complete"}
    assert health_data["sources"][0]["latest_attempt"]["status"] == "failed"
    assert health_data["sources"][0]["latest_attempt"]["scope_id"].startswith("city-scope")
    assert health_data["sources"][0]["last_success_at"] == "2026-09-23T00:00:00Z"
    sparse = PublicSourceHealth.model_validate({"records": {"published": 9}})
    assert sparse.model_dump(exclude_none=True)["records"] == {"published": 9}


def test_public_source_health_route_keeps_sparse_active_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.main.load_source_health",
        lambda: {
            "status": "degraded",
            "records": {"published": 9},
            "sources": [{
                "key": "huntsville_building_permits",
                "status": "failing",
                "coverage": {"status": "complete"},
                "latest_attempt": {
                    "status": "failed", "publication_status": "not_activated",
                },
            }],
        },
    )
    response = TestClient(app).get("/api/source-health")
    assert response.status_code == 200
    assert response.json()["records"] == {"published": 9}
    assert response.json()["sources"][0]["latest_attempt"] == {
        "status": "failed", "publication_status": "not_activated",
    }


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
