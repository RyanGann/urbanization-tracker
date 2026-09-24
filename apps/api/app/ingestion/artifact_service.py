"""Artifact operations compose storage I/O with short durable manifest updates."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.ingestion.artifact_config import configured_sink, effective_sink_id
from app.ingestion.artifact_manifest import ArtifactLeaseLost, ArtifactManifest, UploadLease
from app.ingestion.artifact_progress import LeaseProgress
from app.ingestion.artifact_sink import ArtifactError, hash_stream, verify
from app.ingestion.artifact_upload import upload
from app.ingestion.artifacts import staging_budget_lock


class ArtifactService:
    def __init__(self, settings: Settings, sessions: sessionmaker[Session]) -> None:
        if settings.data_mode != "live" or settings.processed_store_backend != "postgres":
            raise ArtifactError("artifact_configuration")
        self.settings = settings
        self.sink = configured_sink(settings)
        self.sink_id = effective_sink_id(settings, self.sink)
        self.manifest = ArtifactManifest(sessions)

    def staging_path(self, path: Path) -> Path:
        try:
            root = self.settings.ingestion_data_dir.resolve()
            # Relative paths, including those returned by pipeline writers,
            # have one meaning: relative to the worker's current directory.
            # The configured root only constrains the resulting path.
            candidate = path if path.is_absolute() else Path.cwd() / path
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise ArtifactError("artifact_path")
            while candidate != root:
                if not candidate.is_relative_to(root):
                    raise ArtifactError("artifact_path")
                if candidate.is_symlink():
                    raise ArtifactError("artifact_path")
                candidate = candidate.parent
            return resolved
        except (OSError, RuntimeError):
            raise ArtifactError("artifact_path") from None

    def upload_file(
        self,
        *,
        path: Path,
        source_key: str,
        run_id: str,
        artifact_type: str,
        logical_key: str,
        required: bool,
        content_type: str | None = None,
        source_url: str | None = None,
        parent_reference_id: UUID | None = None,
    ) -> UUID:
        path = self.staging_path(path)
        try:
            with path.open("rb") as source:
                blob = hash_stream(source, max_bytes=self.settings.artifact_max_bytes)
        except OSError:
            raise ArtifactError("artifact_path") from None
        reference_id = self.manifest.reserve(
            blob=blob,
            sink_id=self.sink_id,
            source_key=source_key,
            run_id=run_id,
            artifact_type=artifact_type,
            logical_key=logical_key,
            required=required,
            content_type=content_type,
            source_url=source_url,
            parent_reference_id=parent_reference_id,
        )
        self.resume(reference_id, path)
        return reference_id

    def _fail(self, lease: UploadLease, error: ArtifactError) -> None:
        try:
            self.manifest.failed(lease, error)
        except ArtifactLeaseLost:
            # This worker no longer owns state; do not damage the new lease.
            pass

    def resume(self, reference_id: UUID, path: Path) -> None:
        path = self.staging_path(path)
        lease = self.manifest.claim(reference_id, self.sink_id)
        if lease is None:
            _, state = self.manifest.lookup(reference_id, self.sink_id)
            if state == "verified":
                self.audit(reference_id)
                return
            raise ArtifactError("artifact_unavailable")
        try:
            with path.open("rb") as source:
                upload(
                    sink=self.sink,
                    source=source,
                    blob=lease.blob,
                    upload_id=lease.upload_id,
                    parts=lease.parts,
                    checkpoint=lambda upload_id, parts: self.manifest.checkpoint(
                        lease, upload_id, parts
                    ),
                    assert_lease=lambda: self.manifest.heartbeat(lease),
                    mark_uploaded=lambda: self.manifest.uploaded(lease),
                    progress=LeaseProgress(lambda: self.manifest.heartbeat(lease)),
                )
            self.manifest.verified(lease)
        except ArtifactError as error:
            self._fail(lease, error)
            raise
        except OSError:
            path_error = ArtifactError("artifact_path")
            self._fail(lease, path_error)
            raise path_error from None

    def audit(self, reference_id: UUID) -> None:
        lease = self.manifest.claim(reference_id, self.sink_id, audit=True)
        if lease is None:
            raise ArtifactError("artifact_unavailable")
        try:
            verify(
                self.sink,
                lease.blob,
                progress=LeaseProgress(lambda: self.manifest.heartbeat(lease)),
            )
            self.manifest.verified(lease)
        except ArtifactError as error:
            self._fail(lease, error)
            raise

    def cleanup_verified(self, reference_id: UUID, path: Path) -> None:
        """Drop only the exact local bytes backed by a verified durable copy."""
        with staging_budget_lock(self.settings.ingestion_data_dir.resolve()):
            path = self.staging_path(path)
            blob, state = self.manifest.lookup(reference_id, self.sink_id)
            if state != "verified":
                raise ArtifactError("artifact_unavailable")
            try:
                with path.open("rb") as source:
                    local = hash_stream(source, max_bytes=self.settings.artifact_max_bytes)
                if local != blob:
                    raise ArtifactError("artifact_integrity")
                path.unlink()
            except OSError:
                raise ArtifactError("artifact_path") from None
