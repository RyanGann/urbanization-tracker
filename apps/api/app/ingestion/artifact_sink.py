"""Bounded artifact I/O; database leases and publication are owned by callers.

Object keys describe bytes, never source names. Neither HEAD metadata nor a
multipart ETag establishes integrity: verification always hashes downloaded bytes.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import BinaryIO, Literal, Protocol

CHUNK_BYTES = 1024 * 1024
PART_BYTES = 8 * CHUNK_BYTES
MAX_ARTIFACT_BYTES = 8 * 1024 * CHUNK_BYTES
MAX_PARTS = MAX_ARTIFACT_BYTES // PART_BYTES
FailureCode = Literal[
    "artifact_missing",
    "artifact_unavailable",
    "artifact_credentials",
    "artifact_integrity",
    "artifact_too_large",
    "artifact_path",
    "artifact_configuration",
    "artifact_checkpoint",
]


class ArtifactError(RuntimeError):
    """Only bounded, credential-free reason codes may cross the adapter boundary."""

    def __init__(self, code: FailureCode) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class BlobIdentity:
    sha256: str
    byte_size: int

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ArtifactError("artifact_integrity")
        if isinstance(self.byte_size, bool) or not 0 <= self.byte_size <= MAX_ARTIFACT_BYTES:
            raise ArtifactError("artifact_too_large")

    @property
    def key(self) -> str:
        return f"sha256/{self.sha256[:2]}/{self.sha256[2:4]}/{self.sha256}"


@dataclass(frozen=True)
class UploadedPart:
    number: int
    etag: str
    sha256: str
    byte_size: int

    def __post_init__(self) -> None:
        if not 1 <= self.number <= MAX_PARTS or not 1 <= len(self.etag) <= 256:
            raise ArtifactError("artifact_checkpoint")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256) or not 0 <= self.byte_size <= PART_BYTES:
            raise ArtifactError("artifact_checkpoint")


class ArtifactSink(Protocol):
    """Single bounded part per call, allowing a durable checkpoint between calls."""

    @property
    def fingerprint(self) -> str: ...

    def size(self, blob: BlobIdentity) -> int: ...

    def read(self, blob: BlobIdentity) -> Iterator[bytes]: ...

    def begin(self, blob: BlobIdentity) -> str: ...

    def upload_part(
        self, blob: BlobIdentity, upload_id: str, number: int, data: bytes
    ) -> UploadedPart: ...

    def complete(
        self, blob: BlobIdentity, upload_id: str, parts: tuple[UploadedPart, ...]
    ) -> None: ...

    def abort(self, blob: BlobIdentity, upload_id: str) -> None: ...


def hash_stream(stream: BinaryIO, *, max_bytes: int = MAX_ARTIFACT_BYTES) -> BlobIdentity:
    if not 0 <= max_bytes <= MAX_ARTIFACT_BYTES:
        raise ArtifactError("artifact_configuration")
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(min(CHUNK_BYTES, max_bytes - size + 1)):
        size += len(chunk)
        if size > max_bytes:
            raise ArtifactError("artifact_too_large")
        digest.update(chunk)
    return BlobIdentity(digest.hexdigest(), size)


def verify(
    sink: ArtifactSink,
    blob: BlobIdentity,
    *,
    progress: Callable[[], None] = lambda: None,
) -> None:
    progress()
    if sink.size(blob) != blob.byte_size:
        raise ArtifactError("artifact_integrity")
    digest = hashlib.sha256()
    size = 0
    chunks = sink.read(blob)
    try:
        for chunk in chunks:
            progress()
            size += len(chunk)
            if len(chunk) > CHUNK_BYTES or size > blob.byte_size:
                raise ArtifactError("artifact_integrity")
            digest.update(chunk)
    finally:
        # Adapter generators own network/file handles, including early rejection.
        close = getattr(chunks, "close", None)
        if close is not None:
            close()
    if size != blob.byte_size or digest.hexdigest() != blob.sha256:
        raise ArtifactError("artifact_integrity")


def validate_parts(parts: tuple[UploadedPart, ...], blob: BlobIdentity) -> None:
    expected = max(1, (blob.byte_size + PART_BYTES - 1) // PART_BYTES)
    if len(parts) != expected or [part.number for part in parts] != list(range(1, expected + 1)):
        raise ArtifactError("artifact_checkpoint")


def validate_part(number: int, data: bytes, blob: BlobIdentity) -> None:
    expected = max(1, (blob.byte_size + PART_BYTES - 1) // PART_BYTES)
    if not 1 <= number <= expected:
        raise ArtifactError("artifact_checkpoint")
    required_size = PART_BYTES if number < expected else blob.byte_size - (number - 1) * PART_BYTES
    if len(data) != required_size:
        raise ArtifactError("artifact_integrity")
