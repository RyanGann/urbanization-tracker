"""Real PostGIS artifact-manifest checks; invoked by the isolated T01 runner."""

from __future__ import annotations

import hashlib
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import func, select, update

from app.config import get_settings
from app.db import SessionLocal
from app.ingestion.artifact_manifest import (
    ArtifactConflict,
    ArtifactLeaseLost,
    require_verified_references,
)
from app.ingestion.artifact_service import ArtifactService
from app.ingestion.artifact_sink import ArtifactError, BlobIdentity, verify
from app.ingestion.artifact_upload import upload
from app.ingestion.connectors.arcgis import ArcGISLayerConfig, ArcGISRestConnector
from app.ingestion.pipeline import ingest_huntsville
from app.ingestion.source_merge import SourceBatch, merge_postgres_batch
from app.ingestion.sources.huntsville import FEMA_FLOODPLAIN_1PCT, NEW_SUBDIVISIONS
from app.models import (
    ArtifactBlob,
    ArtifactCopy,
    ArtifactReference,
    Phase3CollectionItem,
    ProcessedCollectionItem,
    SourceIngestionBatch,
)
from app.phase3_store import replace_agenda_artifacts
from app.transactional_store import CollectionUnitOfWork


def run_manifest_checks() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="o01-synthetic-") as directory:
        root = Path(directory)
        settings = get_settings().model_copy(
            update={
                "data_mode": "live",
                "processed_store_backend": "postgres",
                "ingestion_data_dir": root,
                "artifact_sink": "local",
                "artifact_local_root": root / "objects",
            }
        )
        service = ArtifactService(settings, SessionLocal)
        manifest = service.manifest
        data = b"synthetic durable provenance\x00\xff"
        blob = BlobIdentity(hashlib.sha256(data).hexdigest(), len(data))
        source = "o01-fixture-" + uuid4().hex
        barrier = Barrier(2)

        def reserve(run: str) -> UUID:
            barrier.wait()
            return manifest.reserve(
                blob=blob,
                sink_id=service.sink_id,
                source_key=source,
                run_id=run,
                artifact_type="raw",
                logical_key="source",
                required=True,
            )

        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(reserve, "run-one")
            second = workers.submit(reserve, "run-two")
            reference_one, reference_two = first.result(), second.result()
        assert reference_one != reference_two
        with SessionLocal() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ArtifactReference)
                    .where(ArtifactReference.source_key == source)
                )
                == 2
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ArtifactBlob)
                    .where(ArtifactBlob.sha256 == blob.sha256)
                )
                == 1
            )
        lease = manifest.claim(reference_one, service.sink_id)
        assert lease is not None
        assert manifest.claim(reference_two, service.sink_id) is None
        with SessionLocal.begin() as session:
            session.execute(
                update(ArtifactCopy)
                .where(
                    ArtifactCopy.blob_id == lease.blob_id,
                    ArtifactCopy.sink_id == service.sink_id,
                )
                .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        try:
            manifest.heartbeat(lease)
        except ArtifactLeaseLost:
            pass
        else:
            raise AssertionError("expired lease renewed without a new claim")
        new_lease = manifest.claim(reference_two, service.sink_id)
        assert new_lease is not None and new_lease.token != lease.token
        try:
            manifest.checkpoint(lease, "stale-worker", ())
        except ArtifactLeaseLost:
            pass
        else:
            raise AssertionError("stale token updated another worker's checkpoint")
        path = root / "raw.bin"
        path.write_bytes(data)
        with path.open("rb") as source_file:
            upload(
                sink=service.sink,
                source=source_file,
                blob=blob,
                upload_id=None,
                parts=(),
                checkpoint=lambda upload_id, parts: manifest.checkpoint(
                    new_lease, upload_id, parts
                ),
                assert_lease=lambda: manifest.heartbeat(new_lease),
                mark_uploaded=lambda: manifest.uploaded(new_lease),
            )
        manifest.verified(new_lease)
        with SessionLocal.begin() as session:
            with CollectionUnitOfWork(session).canonical_mutation():
                require_verified_references(
                    session,
                    reference_ids=(reference_one,),
                    source_key=source,
                    run_id="run-one",
                    sink_id=service.sink_id,
                )
        second_blob = BlobIdentity(hashlib.sha256(b"required text").hexdigest(), 13)
        for required in (True, False):
            try:
                manifest.reserve(
                    blob=second_blob,
                    sink_id=service.sink_id,
                    source_key=source,
                    run_id="run-one",
                    artifact_type="late",
                    logical_key=str(required),
                    required=required,
                )
            except ArtifactConflict:
                pass
            else:
                raise AssertionError("published provenance expanded after sealing")
        new_sink = hashlib.sha256(b"different destination").hexdigest()
        assert (
            manifest.reserve(
                blob=blob,
                sink_id=new_sink,
                source_key=source,
                run_id="run-one",
                artifact_type="raw",
                logical_key="source",
                required=True,
            )
            == reference_one
        )
        reference_three = manifest.reserve(
            blob=blob,
            sink_id=service.sink_id,
            source_key=source,
            run_id="run-three",
            artifact_type="raw",
            logical_key="source",
            required=True,
        )
        text_reference = manifest.reserve(
            blob=second_blob,
            sink_id=service.sink_id,
            source_key=source,
            run_id="run-three",
            artifact_type="text",
            logical_key="text-v1",
            required=True,
            parent_reference_id=reference_three,
        )
        for reference_ids in ((), (reference_three,), (reference_three, text_reference)):
            try:
                with SessionLocal.begin() as session:
                    with CollectionUnitOfWork(session).canonical_mutation():
                        require_verified_references(
                            session,
                            reference_ids=reference_ids,
                            source_key=source,
                            run_id="run-three",
                            sink_id=service.sink_id,
                        )
            except ArtifactError:
                pass
            else:
                raise AssertionError("empty/subset/pending required references activated")
        try:
            manifest.reserve(
                blob=second_blob,
                sink_id=service.sink_id,
                source_key=source,
                run_id="run-one",
                artifact_type="raw",
                logical_key="source",
                required=True,
            )
        except ArtifactConflict:
            pass
        else:
            raise AssertionError("immutable reference changed its bytes")
        gated_settings = settings.model_copy(update={"artifact_durability_required": True})
        gated_batch = SourceBatch(
            run_id="run-three",
            source_key=source,
            scope_id="o01-test",
            scope_version="v1",
            checked_at=datetime.now(UTC),
            records=(),
            required_reference_ids=(reference_three, text_reference),
            artifact_sink_id=service.sink_id,
        )
        with patch("app.ingestion.source_merge.get_settings", return_value=gated_settings):
            try:
                with SessionLocal.begin() as session:
                    merge_postgres_batch(session, gated_batch)
            except ArtifactError as error:
                assert error.code == "artifact_unavailable"
            else:
                raise AssertionError("pending raw/text pair published")
            with SessionLocal() as session:
                assert session.scalar(
                    select(func.count()).select_from(SourceIngestionBatch).where(
                        SourceIngestionBatch.source_key == source,
                        SourceIngestionBatch.run_id == "run-three",
                    )
                ) == 0
            text_path = root / "text.bin"
            text_path.write_bytes(b"required text")
            service.resume(text_reference, text_path)
            with SessionLocal.begin() as session:
                first_merge = merge_postgres_batch(session, gated_batch)
                assert first_merge["replayed"] is False
            with SessionLocal.begin() as session:
                replay = merge_postgres_batch(session, gated_batch)
                assert replay["replayed"] is True
        agenda_run = "run-agenda-" + uuid4().hex
        agenda_source = "huntsville_planning_agendas"
        agenda_pdf = service.upload_file(
            path=path,
            source_key=agenda_source,
            run_id=agenda_run,
            artifact_type="source_pdf",
            logical_key="agenda-pdf",
            required=True,
        )
        agenda_text_blob = BlobIdentity(hashlib.sha256(b"new agenda text").hexdigest(), 15)
        agenda_text = manifest.reserve(
            blob=agenda_text_blob,
            sink_id=service.sink_id,
            source_key=agenda_source,
            run_id=agenda_run,
            artifact_type="extracted_text",
            logical_key="agenda-text",
            required=True,
            parent_reference_id=agenda_pdf,
        )
        agenda_collections = (
            "source_documents",
            "agenda_staged_records",
            "duplicate_candidates",
            "agenda_health",
        )

        def agenda_rows() -> dict[str, list[dict[str, object]]]:
            with SessionLocal() as session:
                return {
                    name: [
                        row.payload_json
                        for row in session.scalars(
                            select(Phase3CollectionItem)
                            .where(Phase3CollectionItem.collection_name == name)
                            .order_by(Phase3CollectionItem.sort_order, Phase3CollectionItem.id)
                        )
                    ]
                    for name in agenda_collections
                }

        with patch("app.phase3_store.get_settings", return_value=settings):
            replace_agenda_artifacts(
                source_documents=[{"id": "prior-agenda", "title": "Prior"}],
                staged_records=[{"id": "prior-item", "title": "Prior item"}],
                duplicate_candidates=[{"id": "prior-candidate", "title": "Prior candidate"}],
                health={"id": "prior-health", "status": "healthy"},
            )
        prior_agenda = agenda_rows()
        next_documents = [{"id": "next-agenda", "title": "Next"}]
        next_records = [{"id": "next-item", "title": "Next item"}]
        next_candidates = [{"id": "next-candidate", "title": "Next candidate"}]
        next_health = {"id": "next-health", "status": "healthy"}

        def publish_next_agenda() -> None:
            replace_agenda_artifacts(
                source_documents=next_documents,
                staged_records=next_records,
                duplicate_candidates=next_candidates,
                health=next_health,
                run_id=agenda_run,
                artifact_sink_id=service.sink_id,
                required_reference_ids=(agenda_pdf, agenda_text),
            )

        with patch("app.phase3_store.get_settings", return_value=gated_settings):
            try:
                publish_next_agenda()
            except ArtifactError as error:
                assert error.code == "artifact_unavailable"
            else:
                raise AssertionError("pending agenda text published over prior revision")
            assert agenda_rows() == prior_agenda
            text_path = root / "agenda-text.bin"
            text_path.write_bytes(b"new agenda text")
            service.resume(agenda_text, text_path)
            publish_next_agenda()
        published_agenda = agenda_rows()
        assert published_agenda["source_documents"] == next_documents
        assert published_agenda["agenda_staged_records"] == next_records
        assert published_agenda["duplicate_candidates"] == next_candidates
        assert published_agenda["agenda_health"] == [next_health]

        retry_data = b"fresh upload after vanished multipart checkpoint"
        retry_blob = BlobIdentity(hashlib.sha256(retry_data).hexdigest(), len(retry_data))
        retry_reference = manifest.reserve(
            blob=retry_blob,
            sink_id=service.sink_id,
            source_key=source,
            run_id="run-invalid-multipart-checkpoint",
            artifact_type="raw",
            logical_key="source",
            required=True,
        )
        invalid_lease = manifest.claim(retry_reference, service.sink_id)
        assert invalid_lease is not None
        manifest.checkpoint(invalid_lease, "removed-remote-upload", ())
        manifest.failed(invalid_lease, ArtifactError("artifact_checkpoint"))
        with SessionLocal.begin() as session:
            copy = session.get(ArtifactCopy, (invalid_lease.blob_id, service.sink_id))
            assert copy is not None
            assert copy.state == "failed"
            assert copy.multipart_upload_id is None and copy.multipart_parts == []
            # Advance only this disposable fixture past its bounded retry delay.
            copy.next_attempt_at = None
        retry_lease = manifest.claim(retry_reference, service.sink_id)
        assert retry_lease is not None
        assert retry_lease.upload_id is None and retry_lease.parts == ()
        retry_path = root / "retry-raw.bin"
        retry_path.write_bytes(retry_data)
        with retry_path.open("rb") as retry_file:
            upload(
                sink=service.sink,
                source=retry_file,
                blob=retry_blob,
                upload_id=retry_lease.upload_id,
                parts=retry_lease.parts,
                checkpoint=lambda upload_id, parts: manifest.checkpoint(
                    retry_lease, upload_id, parts
                ),
                assert_lease=lambda: manifest.heartbeat(retry_lease),
                mark_uploaded=lambda: manifest.uploaded(retry_lease),
            )
        manifest.verified(retry_lease)
        verify(service.sink, retry_blob)
        path.unlink()
        service.audit(reference_one)
        verify(service.sink, blob)
        assert not path.exists()
        return {
            "concurrent_runs_preserved": True,
            "single_blob_multiple_references": True,
            "expired_lease_cannot_renew": True,
            "stale_completion_denied": True,
            "exact_required_set_enforced": True,
            "pending_artifact_blocks_gate": True,
            "immutable_observation_conflict": True,
            "audit_without_staging": True,
            "late_required_and_optional_refs_rejected": True,
            "sealed_retry_new_sink_allowed": True,
            "pending_batch_has_no_replay_marker": True,
            "verified_retry_merges_once": True,
            "pending_agenda_preserves_prior_revision": True,
            "verified_agenda_replaces_four_collections_atomically": True,
            "invalid_multipart_checkpoint_recovers": True,
        }


def run_context_hold_checks() -> dict[str, bool]:
    """A failed required floodplain upload cannot erase an existing proximity flag."""
    with tempfile.TemporaryDirectory(prefix="o01-context-hold-") as directory:
        root = Path(directory)
        settings = get_settings().model_copy(
            update={
                "data_mode": "live",
                "processed_store_backend": "postgres",
                "phase3_store_backend": "postgres",
                "ingestion_data_dir": root,
                "artifact_sink": "local",
                "artifact_local_root": root / "objects",
                "artifact_durability_required": True,
            }
        )
        polygon = {
            "type": "Polygon",
            "coordinates": [[
                [-86.600, 34.700], [-86.599, 34.700], [-86.599, 34.701],
                [-86.600, 34.701], [-86.600, 34.700],
            ]],
        }
        source_id = "o01-context-" + uuid4().hex

        class SyntheticConnector:
            title = "Prior subdivision"

            def get_layer_metadata(self, _config: ArcGISLayerConfig) -> dict[str, object]:
                return {"currentVersion": 11, "geometryType": "esriGeometryPolygon"}

            def get_count(self, config: ArcGISLayerConfig) -> int:
                return len(self.fetch_geojson(config)["features"])

            def fetch_geojson(self, config: ArcGISLayerConfig) -> dict[str, Any]:
                if config.key == NEW_SUBDIVISIONS.key:
                    features = [{
                        "type": "Feature",
                        "geometry": polygon,
                        "properties": {"SubdID": source_id, "Subdivision": self.title},
                    }]
                elif config.key == FEMA_FLOODPLAIN_1PCT.key:
                    features = [{
                        "type": "Feature",
                        "geometry": polygon,
                        "properties": {"OBJECTID": 1},
                    }]
                else:
                    features = []
                return {"type": "FeatureCollection", "features": features}

        connector = SyntheticConnector()

        def published_record() -> dict[str, Any]:
            with SessionLocal() as session:
                rows = session.scalars(
                    select(ProcessedCollectionItem).where(
                        ProcessedCollectionItem.collection_name == "development_records"
                    )
                ).all()
                matched = [
                    row.payload_json for row in rows
                    if row.payload_json.get("source_record_id") == source_id
                ]
                assert len(matched) == 1
                return deepcopy(matched[0])

        with (
            patch("app.ingestion.pipeline.get_settings", return_value=settings),
            patch("app.ingestion.artifacts.get_settings", return_value=settings),
            patch("app.ingestion.source_merge.get_settings", return_value=settings),
            patch(
                "app.ingestion.pipeline.iso_now",
                side_effect=[
                    "2026-09-24T01:00:00+00:00",
                    "2026-09-24T01:01:00+00:00",
                    "2026-09-24T01:02:00+00:00",
                ],
            ),
        ):
            first = ingest_huntsville(
                data_dir=root, connector=cast(ArcGISRestConnector, connector)
            )
            prior = published_record()
            assert prior["title"] == "Prior subdivision"
            assert {flag["flag_type"] for flag in prior["proximity_flags"]} == {
                "intersects_floodplain"
            }
            assert first["batches"][NEW_SUBDIVISIONS.key]["replayed"] is False
            connector.title = "Unsafe replacement"
            original_upload = ArtifactService.upload_file

            def fail_flood_upload(service: ArtifactService, **kwargs: Any) -> UUID:
                if kwargs["source_key"] == FEMA_FLOODPLAIN_1PCT.key:
                    raise ArtifactError("artifact_unavailable")
                return original_upload(service, **kwargs)

            with patch.object(ArtifactService, "upload_file", fail_flood_upload):
                held = ingest_huntsville(
                    data_dir=root, connector=cast(ArcGISRestConnector, connector)
                )
            assert NEW_SUBDIVISIONS.key not in held["batches"]
            assert published_record() == prior
            assert any(
                "environmental_context_unverified" in source["validation_errors"]
                for source in held["sources"]
                if source["key"] == NEW_SUBDIVISIONS.key
            )
            connector.title = "Recovered subdivision"
            recovered = ingest_huntsville(
                data_dir=root, connector=cast(ArcGISRestConnector, connector)
            )
            current = published_record()
            assert current["title"] == "Recovered subdivision"
            assert {flag["flag_type"] for flag in current["proximity_flags"]} == {
                "intersects_floodplain"
            }
            assert recovered["batches"][NEW_SUBDIVISIONS.key]["replayed"] is False
        return {
            "failed_environmental_upload_holds_development": True,
            "prior_verified_proximity_preserved": True,
            "successful_retry_publishes_once_with_context": True,
        }


if __name__ == "__main__":
    print(json.dumps({**run_manifest_checks(), **run_context_hold_checks()}, sort_keys=True))
