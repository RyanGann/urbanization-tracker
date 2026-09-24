"""Disposable Garage/PostGIS upload, restart and copied-restore proof."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select, update

from app.config import get_settings
from app.db import SessionLocal
from app.ingestion.artifact_config import configured_sink
from app.ingestion.artifact_manifest import require_verified_references
from app.ingestion.artifact_s3 import S3ArtifactSink
from app.ingestion.artifact_service import ArtifactService
from app.ingestion.artifact_sink import (
    PART_BYTES,
    ArtifactError,
    BlobIdentity,
    UploadedPart,
    hash_stream,
    verify,
)
from app.ingestion.artifact_upload import upload
from app.models import ArtifactBlob, ArtifactCopy, ArtifactReference
from app.transactional_store import CollectionUnitOfWork

ROOT = Path("/o01-data")
RESULT = ROOT / "results.json"
SOURCE_BUCKET = "integration-artifacts"
RESTORE_BUCKET = "integration-artifacts-restore"


def _service() -> ArtifactService:
    settings = get_settings().model_copy(
        update={
            "data_mode": "live",
            "processed_store_backend": "postgres",
            "ingestion_data_dir": ROOT / "staging",
        }
    )
    return ArtifactService(settings, SessionLocal)


def _wrong_credentials(service: ArtifactService) -> None:
    settings = service.settings
    assert settings.artifact_s3_secret_key is not None
    assert settings.artifact_s3_access_key is not None
    wrong = S3ArtifactSink(
        endpoint=str(settings.artifact_s3_endpoint),
        bucket=str(settings.artifact_s3_bucket),
        region=settings.artifact_s3_region,
        access_key=settings.artifact_s3_access_key.get_secret_value(),
        secret_key="invalid-test-secret",
        allow_http=True,
    )
    try:
        wrong._call("list_objects_v2", MaxKeys=1)
    except ArtifactError as error:
        assert error.code == "artifact_credentials"
    else:
        raise AssertionError("wrong Garage credential was accepted")


def _rows(reference_ids: list[str]) -> list[tuple[ArtifactReference, ArtifactBlob]]:
    ids = [UUID(value) for value in reference_ids]
    with SessionLocal() as session:
        rows = session.execute(
            select(ArtifactReference, ArtifactBlob)
            .join(ArtifactBlob, ArtifactBlob.id == ArtifactReference.blob_id)
            .where(ArtifactReference.id.in_(ids))
        ).all()
        assert len(rows) == len(ids)
        return [(row.ArtifactReference, row.ArtifactBlob) for row in rows]


def _load_expected() -> dict[str, object]:
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert isinstance(payload.get("reference_ids"), list)
    return payload


def _empty_staging() -> None:
    stage = ROOT / "staging"
    assert stage.is_dir() and not any(stage.iterdir())


def probe() -> dict[str, bool]:
    service = _service()
    assert isinstance(service.sink, S3ArtifactSink)
    service.sink.client.list_objects_v2(Bucket=service.sink.bucket, MaxKeys=1)
    _wrong_credentials(service)
    return {"private_bucket_reachable": True, "wrong_credentials_rejected": True}


def initial() -> dict[str, object]:
    service = _service()
    assert service.settings.artifact_s3_bucket == SOURCE_BUCKET
    stage = ROOT / "staging"
    stage.mkdir(parents=True, exist_ok=True)
    assert not any(stage.iterdir())
    source_key = "o01-garage-" + uuid4().hex
    run_id = "run-" + uuid4().hex
    inputs = (
        ("empty", b""),
        ("binary", b"binary\x00\xff"),
        ("multipart", b"m" * (PART_BYTES + 17)),
    )
    reference_ids: list[str] = []
    blobs: dict[str, dict[str, object]] = {}
    paths: list[Path] = []
    for logical_key, data in inputs:
        path = stage / f"{logical_key}.bin"
        path.write_bytes(data)
        paths.append(path)
        reference_id = service.upload_file(
            path=path,
            source_key=source_key,
            run_id=run_id,
            artifact_type="source_payload",
            logical_key=logical_key,
            required=True,
        )
        reference_ids.append(str(reference_id))
        blobs[logical_key] = {"sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}
    # Duplicate bytes retain a distinct run observation with one immutable blob.
    duplicate_run = "run-" + uuid4().hex
    duplicate = service.upload_file(
        path=paths[1],
        source_key=source_key,
        run_id=duplicate_run,
        artifact_type="source_payload",
        logical_key="binary",
        required=True,
    )
    reference_ids.append(str(duplicate))
    # Stop after the first remote multipart part and its durable checkpoint.
    interrupted_data = b"i" * (PART_BYTES + 19)
    interrupted_path = stage / "interrupted.bin"
    interrupted_path.write_bytes(interrupted_data)
    paths.append(interrupted_path)
    with interrupted_path.open("rb") as handle:
        interrupted_blob = hash_stream(handle)
    interrupted_reference = service.manifest.reserve(
        blob=interrupted_blob,
        sink_id=service.sink_id,
        source_key=source_key,
        run_id=run_id,
        artifact_type="source_payload",
        logical_key="interrupted",
        required=True,
    )
    lease = service.manifest.claim(interrupted_reference, service.sink_id)
    assert lease is not None

    def checkpoint(upload_id: str, parts: tuple[UploadedPart, ...]) -> None:
        service.manifest.checkpoint(lease, upload_id, parts)
        if len(parts) == 1:
            raise InterruptedError("synthetic worker interruption")

    try:
        with interrupted_path.open("rb") as handle:
            upload(
                sink=service.sink,
                source=handle,
                blob=interrupted_blob,
                upload_id=None,
                parts=(),
                checkpoint=checkpoint,
                assert_lease=lambda: service.manifest.heartbeat(lease),
            )
    except InterruptedError:
        pass
    else:
        raise AssertionError("multipart interruption did not occur")
    with SessionLocal.begin() as session:
        session.execute(
            update(ArtifactCopy)
            .where(ArtifactCopy.blob_id == lease.blob_id, ArtifactCopy.sink_id == service.sink_id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    service.resume(interrupted_reference, interrupted_path)
    reference_ids.append(str(interrupted_reference))
    blobs["interrupted"] = {
        "sha256": interrupted_blob.sha256,
        "byte_size": interrupted_blob.byte_size,
    }
    with SessionLocal.begin() as session:
        with CollectionUnitOfWork(session).canonical_mutation():
            require_verified_references(
                session,
                reference_ids=tuple(
                    UUID(value) for value in reference_ids if value != str(duplicate)
                ),
                source_key=source_key,
                run_id=run_id,
                sink_id=service.sink_id,
            )
            require_verified_references(
                session,
                reference_ids=(duplicate,),
                source_key=source_key,
                run_id=duplicate_run,
                sink_id=service.sink_id,
            )
    with SessionLocal() as session:
        count = session.scalar(
            select(func.count()).select_from(ArtifactBlob).where(
                ArtifactBlob.sha256 == blobs["binary"]["sha256"]
            )
        )
        assert count == 1
    assert isinstance(service.sink, S3ArtifactSink)
    mismatch = BlobIdentity(hashlib.sha256(b"expected").hexdigest(), 8)
    service.sink.client.put_object(Bucket=SOURCE_BUCKET, Key=mismatch.key, Body=b"corrupt!")
    try:
        verify(service.sink, mismatch)
    except ArtifactError as error:
        assert error.code == "artifact_integrity"
    else:
        raise AssertionError("corrupt Garage bytes passed checksum verification")
    finally:
        service.sink.client.delete_object(Bucket=SOURCE_BUCKET, Key=mismatch.key)
    _wrong_credentials(service)
    for path in paths:
        path.unlink()
    _empty_staging()
    result: dict[str, object] = {
        "source_key": source_key,
        "run_id": run_id,
        "duplicate_run_id": duplicate_run,
        "reference_ids": reference_ids,
        "blobs": blobs,
        "sink_id": service.sink_id,
        "staging_empty": True,
        "interrupted_retry_verified": True,
        "wrong_credentials_rejected": True,
        "checksum_mismatch_rejected": True,
    }
    RESULT.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def restart() -> dict[str, bool]:
    expected = _load_expected()
    _empty_staging()
    service = _service()
    assert service.sink_id == expected["sink_id"]
    for reference, blob in _rows(expected["reference_ids"]):  # type: ignore[arg-type]
        assert reference.source_key == expected["source_key"]
        service.audit(reference.id)
        verify(service.sink, BlobIdentity(blob.sha256, blob.byte_size))
    _wrong_credentials(service)
    _empty_staging()
    return {"restart_without_staging": True, "manifest_and_downloaded_bytes_match": True}


def restore() -> dict[str, bool]:
    expected = _load_expected()
    _empty_staging()
    target_service = _service()
    assert target_service.settings.artifact_s3_bucket == RESTORE_BUCKET
    assert target_service.sink_id != expected["sink_id"]
    assert isinstance(target_service.sink, S3ArtifactSink)
    source_settings = target_service.settings.model_copy(
        update={"artifact_s3_bucket": SOURCE_BUCKET}
    )
    source_sink = configured_sink(source_settings)
    assert isinstance(source_sink, S3ArtifactSink)
    reference_ids = expected["reference_ids"]
    assert isinstance(reference_ids, list)
    rows = _rows(reference_ids)
    unique_blobs: dict[UUID, ArtifactBlob] = {blob.id: blob for _, blob in rows}
    for blob in unique_blobs.values():
        identity = BlobIdentity(blob.sha256, blob.byte_size)
        verify(source_sink, identity)
        try:
            target_service.sink.client.copy_object(
                Bucket=RESTORE_BUCKET,
                Key=identity.key,
                CopySource={"Bucket": SOURCE_BUCKET, "Key": identity.key},
            )
        except Exception:
            raise AssertionError("copied_restore_object_transfer_failed") from None
        verify(target_service.sink, identity)
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        for blob in unique_blobs.values():
            session.add(
                ArtifactCopy(
                    blob_id=blob.id,
                    sink_id=target_service.sink_id,
                    object_key=BlobIdentity(blob.sha256, blob.byte_size).key,
                    state="verified",
                    uploaded_at=now,
                    verified_at=now,
                    last_audit_at=now,
                )
            )
    grouped: dict[tuple[str, str], list[UUID]] = defaultdict(list)
    expected_blobs = expected["blobs"]
    assert isinstance(expected_blobs, dict)
    expected_hashes = {
        str(item["sha256"]) for item in expected_blobs.values() if isinstance(item, dict)
    }
    for reference, blob in rows:
        assert blob.sha256 in expected_hashes
        grouped[(reference.source_key, reference.run_id)].append(reference.id)
        target_service.audit(reference.id)
    with SessionLocal.begin() as session:
        with CollectionUnitOfWork(session).canonical_mutation():
            for (source_key, run_id), ids in grouped.items():
                require_verified_references(
                    session,
                    reference_ids=tuple(ids),
                    source_key=source_key,
                    run_id=run_id,
                    sink_id=target_service.sink_id,
                )
    _empty_staging()
    return {
        "copied_database_references": True,
        "copied_object_bytes_verified": True,
        "restore_without_staging": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("probe", "initial", "restart", "restore"))
    mode = parser.parse_args().mode
    output = {"probe": probe, "initial": initial, "restart": restart, "restore": restore}[mode]()
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
