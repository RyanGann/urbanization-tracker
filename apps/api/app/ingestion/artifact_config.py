"""Resolve storage configuration only for artifact operations, never API startup."""

from __future__ import annotations

import hashlib
import json

from app.config import Settings
from app.ingestion.artifact_local import LocalArtifactSink
from app.ingestion.artifact_sink import ArtifactError, ArtifactSink


def effective_sink_id(settings: Settings, sink: ArtifactSink) -> str:
    identity = [settings.artifact_sink_id, sink.fingerprint]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def configured_sink(settings: Settings) -> ArtifactSink:
    if settings.artifact_sink == "local":
        return LocalArtifactSink(
            settings.artifact_local_root or settings.ingestion_data_dir / "artifact-objects"
        )
    from app.ingestion.artifact_s3 import S3ArtifactSink

    if (
        not settings.artifact_s3_endpoint
        or not settings.artifact_s3_bucket
        or not settings.artifact_s3_access_key
        or not settings.artifact_s3_secret_key
    ):
        raise ArtifactError("artifact_configuration")
    return S3ArtifactSink(
        endpoint=settings.artifact_s3_endpoint,
        bucket=settings.artifact_s3_bucket,
        region=settings.artifact_s3_region,
        access_key=settings.artifact_s3_access_key.get_secret_value(),
        secret_key=settings.artifact_s3_secret_key.get_secret_value(),
        allow_http=settings.artifact_s3_allow_http,
    )
