"""Stream a stable byte plan through a caller-owned durable upload lease."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import BinaryIO

from app.ingestion.artifact_sink import (
    PART_BYTES,
    ArtifactError,
    ArtifactSink,
    BlobIdentity,
    UploadedPart,
    verify,
)


@dataclass(frozen=True)
class PartIdentity:
    sha256: str
    byte_size: int


def plan_parts(
    source: BinaryIO,
    blob: BlobIdentity,
    *,
    progress: Callable[[], None] = lambda: None,
) -> tuple[PartIdentity, ...]:
    progress()
    source.seek(0)
    digest = hashlib.sha256()
    total = 0
    plan: list[PartIdentity] = []
    while data := source.read(PART_BYTES):
        progress()
        total += len(data)
        if total > blob.byte_size:
            raise ArtifactError("artifact_integrity")
        digest.update(data)
        plan.append(PartIdentity(hashlib.sha256(data).hexdigest(), len(data)))
    if digest.hexdigest() != blob.sha256 or total != blob.byte_size:
        raise ArtifactError("artifact_integrity")
    if not plan:
        plan.append(PartIdentity(hashlib.sha256(b"").hexdigest(), 0))
    return tuple(plan)


def upload(
    *,
    sink: ArtifactSink,
    source: BinaryIO,
    blob: BlobIdentity,
    upload_id: str | None,
    parts: tuple[UploadedPart, ...],
    checkpoint: Callable[[str, tuple[UploadedPart, ...]], None],
    assert_lease: Callable[[], None],
    mark_uploaded: Callable[[], None] = lambda: None,
    progress: Callable[[], None] = lambda: None,
) -> None:
    """All callbacks use short DB transactions; the adapter never owns a Session.

    Plan before any remote mutation. Every worker sharing a resumable upload is
    then restricted to the same bytes per part, even if its local source changes.
    """
    plan = plan_parts(source, blob, progress=progress)
    if len(parts) > len(plan) or (parts and upload_id is None):
        raise ArtifactError("artifact_checkpoint")
    for index, part in enumerate(parts):
        expected = plan[index]
        if (
            part.number != index + 1
            or part.sha256 != expected.sha256
            or part.byte_size != expected.byte_size
        ):
            raise ArtifactError("artifact_integrity")
    assert_lease()
    try:
        verify(sink, blob, progress=progress)
    except ArtifactError as error:
        if error.code != "artifact_missing":
            raise
    else:
        # A previous attempt may have completed remotely before its DB commit.
        return
    if upload_id is None:
        upload_id = sink.begin(blob)
        try:
            checkpoint(upload_id, ())
        except Exception:
            # The ID was never durably recorded. Best-effort cleanup avoids an
            # orphaned multipart upload that no future worker can discover.
            try:
                sink.abort(blob, upload_id)
            except (ArtifactError, OSError):
                pass
            raise
    source.seek(0)
    digest = hashlib.sha256()
    completed = list(parts)
    for index, expected in enumerate(plan):
        data = source.read(PART_BYTES)
        if len(data) != expected.byte_size or hashlib.sha256(data).hexdigest() != expected.sha256:
            raise ArtifactError("artifact_integrity")
        digest.update(data)
        assert_lease()
        if index >= len(parts):
            part = sink.upload_part(blob, upload_id, index + 1, data)
            completed.append(part)
            checkpoint(upload_id, tuple(completed))
    if source.read(1) or digest.hexdigest() != blob.sha256:
        raise ArtifactError("artifact_integrity")
    assert_lease()
    sink.complete(blob, upload_id, tuple(completed))
    mark_uploaded()
    verify(sink, blob, progress=progress)
