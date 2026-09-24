"""Local developer sink with immutable objects and restartable part staging."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from app.ingestion.artifact_sink import (
    CHUNK_BYTES,
    ArtifactError,
    BlobIdentity,
    UploadedPart,
    hash_stream,
    validate_part,
    validate_parts,
    verify,
)


class LocalArtifactSink:
    def __init__(self, root: Path) -> None:
        try:
            self.root = root.resolve()
            self.root.mkdir(parents=True, exist_ok=True)
        except (OSError, RuntimeError):
            raise ArtifactError("artifact_path") from None

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"local-v1:{self.root}".encode()).hexdigest()

    def _path(self, relative: str) -> Path:
        path = self.root / relative
        if not path.resolve().is_relative_to(self.root):
            raise ArtifactError("artifact_path")
        current = path
        while current != self.root:
            if current.is_symlink():
                raise ArtifactError("artifact_path")
            current = current.parent
        return path

    def _upload(self, blob: BlobIdentity, upload_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", upload_id):
            raise ArtifactError("artifact_checkpoint")
        return self._path(f".pending/{blob.sha256}/{upload_id}")

    def size(self, blob: BlobIdentity) -> int:
        try:
            return self._path(blob.key).stat().st_size
        except FileNotFoundError:
            raise ArtifactError("artifact_missing") from None
        except OSError:
            raise ArtifactError("artifact_unavailable") from None

    def read(self, blob: BlobIdentity) -> Iterator[bytes]:
        try:
            with self._path(blob.key).open("rb") as source:
                while chunk := source.read(CHUNK_BYTES):
                    yield chunk
        except FileNotFoundError:
            raise ArtifactError("artifact_missing") from None
        except OSError:
            raise ArtifactError("artifact_unavailable") from None

    def begin(self, blob: BlobIdentity) -> str:
        upload_id = uuid4().hex
        try:
            self._upload(blob, upload_id).mkdir(parents=True, exist_ok=False)
        except OSError:
            raise ArtifactError("artifact_unavailable") from None
        return upload_id

    def upload_part(
        self, blob: BlobIdentity, upload_id: str, number: int, data: bytes
    ) -> UploadedPart:
        validate_part(number, data, blob)
        path = self._upload(blob, upload_id)
        if not path.is_dir():
            raise ArtifactError("artifact_checkpoint")
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path, delete=False) as output:
                temporary = output.name
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path / str(number))
        except FileNotFoundError:
            raise ArtifactError("artifact_checkpoint") from None
        except OSError:
            raise ArtifactError("artifact_unavailable") from None
        finally:
            if temporary is not None:
                self._remove_temporary(temporary)
        digest = hashlib.sha256(data).hexdigest()
        return UploadedPart(number, digest, digest, len(data))

    def complete(self, blob: BlobIdentity, upload_id: str, parts: tuple[UploadedPart, ...]) -> None:
        validate_parts(parts, blob)
        pending = self._upload(blob, upload_id)
        if not pending.is_dir():
            raise ArtifactError("artifact_checkpoint")
        target = self._path(blob.key)
        temporary: str | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                temporary = output.name
                for part in parts:
                    digest = hashlib.sha256()
                    try:
                        source = self._path(
                            f".pending/{blob.sha256}/{upload_id}/{part.number}"
                        ).open("rb")
                    except FileNotFoundError:
                        raise ArtifactError("artifact_checkpoint") from None
                    with source:
                        total = 0
                        while chunk := source.read(CHUNK_BYTES):
                            total += len(chunk)
                            if total > 8 * CHUNK_BYTES:
                                raise ArtifactError("artifact_integrity")
                            digest.update(chunk)
                            output.write(chunk)
                    if digest.hexdigest() != part.sha256 or total != part.byte_size:
                        raise ArtifactError("artifact_integrity")
                output.flush()
                os.fsync(output.fileno())
            with Path(temporary).open("rb") as source:
                if hash_stream(source, max_bytes=blob.byte_size) != blob:
                    raise ArtifactError("artifact_integrity")
            try:
                # Exclusive installation: never replace a prior verified object.
                os.link(temporary, target)
            except FileExistsError:
                verify(self, blob)
            self.abort(blob, upload_id)
        except OSError:
            raise ArtifactError("artifact_unavailable") from None
        finally:
            if temporary is not None:
                self._remove_temporary(temporary)

    @staticmethod
    def _remove_temporary(path: str) -> None:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            raise ArtifactError("artifact_unavailable") from None

    def abort(self, blob: BlobIdentity, upload_id: str) -> None:
        pending = self._upload(blob, upload_id)
        try:
            if pending.exists():
                # Only this exact upload's bounded numeric part files; no recursive delete.
                for part in pending.iterdir():
                    if part.name.isdecimal() and part.is_file() and not part.is_symlink():
                        part.unlink()
                pending.rmdir()
        except OSError:
            raise ArtifactError("artifact_unavailable") from None
