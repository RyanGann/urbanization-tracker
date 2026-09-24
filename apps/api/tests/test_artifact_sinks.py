from __future__ import annotations

import hashlib
import io
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.ingestion.artifact_local import LocalArtifactSink
from app.ingestion.artifact_progress import LeaseProgress
from app.ingestion.artifact_sink import (
    CHUNK_BYTES,
    PART_BYTES,
    ArtifactError,
    BlobIdentity,
    UploadedPart,
    hash_stream,
    verify,
)
from app.ingestion.artifact_upload import upload


@pytest.mark.parametrize("data", [b"", b"binary\x00\xff", b"a" * (PART_BYTES + 17)])
def test_local_roundtrip_and_resume(tmp_path: Path, data: bytes) -> None:
    blob = hash_stream(io.BytesIO(data))
    sink = LocalArtifactSink(tmp_path)
    upload = sink.begin(blob)
    first = sink.upload_part(blob, upload, 1, data[:PART_BYTES])
    # Reconstructing the adapter models a worker restart; parts remain on disk.
    resumed = LocalArtifactSink(tmp_path)
    parts = (first,)
    if len(data) > PART_BYTES:
        parts += (resumed.upload_part(blob, upload, 2, data[PART_BYTES:]),)
    resumed.complete(blob, upload, parts)
    verify(resumed, blob)
    assert b"".join(resumed.read(blob)) == data
    assert resumed.fingerprint == sink.fingerprint
    assert not (tmp_path / ".pending" / blob.sha256 / upload).exists()


def test_local_existing_corruption_is_never_overwritten(tmp_path: Path) -> None:
    data = b"original"
    blob = hash_stream(io.BytesIO(data))
    sink = LocalArtifactSink(tmp_path)
    target = tmp_path / blob.key
    target.parent.mkdir(parents=True)
    target.write_bytes(b"corrupt!")
    upload = sink.begin(blob)
    part = sink.upload_part(blob, upload, 1, data)
    with pytest.raises(ArtifactError, match="artifact_integrity"):
        sink.complete(blob, upload, (part,))
    assert target.read_bytes() == b"corrupt!"


def test_changed_bytes_and_size_limit(tmp_path: Path) -> None:
    sink = LocalArtifactSink(tmp_path)
    blob = BlobIdentity(hashlib.sha256(b"expected").hexdigest(), 8)
    upload = sink.begin(blob)
    part = sink.upload_part(blob, upload, 1, b"modified")
    with pytest.raises(ArtifactError, match="artifact_integrity"):
        sink.complete(blob, upload, (part,))
    assert not (tmp_path / blob.key).exists()
    with pytest.raises(ArtifactError, match="artifact_too_large"):
        hash_stream(io.BytesIO(b"12345"), max_bytes=4)


def test_local_path_escape_and_destination_identity(tmp_path: Path) -> None:
    sink = LocalArtifactSink(tmp_path / "store")
    blob = hash_stream(io.BytesIO(b"a"))
    with pytest.raises(ArtifactError, match="artifact_checkpoint"):
        sink.upload_part(blob, "../private", 1, b"a")
    outside = tmp_path / "outside"
    outside.mkdir()
    (sink.root / "sha256").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactError, match="artifact_path"):
        sink.size(blob)
    assert LocalArtifactSink(outside).fingerprint != sink.fingerprint


def test_resume_rejects_changed_checkpoint_prefix_without_touching_verified_copy(
    tmp_path: Path,
) -> None:
    data = b"a" * PART_BYTES + b"original suffix"
    blob = hash_stream(io.BytesIO(data))
    sink = LocalArtifactSink(tmp_path)
    checkpointed: tuple[str, tuple[UploadedPart, ...]] | None = None

    def stop_after_part(upload_id: str, parts: tuple[UploadedPart, ...]) -> None:
        nonlocal checkpointed
        checkpointed = (upload_id, parts)
        if parts:
            raise InterruptedError("synthetic worker exit")

    with pytest.raises(InterruptedError):
        upload(
            sink=sink,
            source=io.BytesIO(data),
            blob=blob,
            upload_id=None,
            parts=(),
            checkpoint=stop_after_part,
            assert_lease=lambda: None,
        )
    assert checkpointed is not None
    # Another successful worker installs the same expected bytes.
    upload(
        sink=sink,
        source=io.BytesIO(data),
        blob=blob,
        upload_id=None,
        parts=(),
        checkpoint=lambda *_: None,
        assert_lease=lambda: None,
    )
    with pytest.raises(ArtifactError, match="artifact_integrity"):
        upload(
            sink=sink,
            source=io.BytesIO(b"b" + data[1:]),
            blob=blob,
            upload_id=checkpointed[0],
            parts=checkpointed[1],
            checkpoint=lambda *_: None,
            assert_lease=lambda: None,
        )
    verify(sink, blob)
    assert b"".join(sink.read(blob)) == data


def test_slow_verification_heartbeats_beyond_original_lease(tmp_path: Path) -> None:
    now = [0.0]
    expires = [180.0]
    heartbeat_times: list[float] = []

    def heartbeat() -> None:
        if now[0] >= expires[0]:
            raise ArtifactError("artifact_checkpoint")
        heartbeat_times.append(now[0])
        expires[0] = now[0] + 180

    class SlowSink(LocalArtifactSink):
        def read(self, blob: BlobIdentity) -> Iterator[bytes]:
            for chunk in super().read(blob):
                now[0] += 40
                yield chunk

    sink = SlowSink(tmp_path)
    data = b"s" * (7 * CHUNK_BYTES)
    blob = hash_stream(io.BytesIO(data))
    path = sink.root / blob.key
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    verify(sink, blob, progress=LeaseProgress(heartbeat, clock=lambda: now[0]))
    assert now[0] > 180
    assert len(heartbeat_times) == 8
    assert expires[0] > now[0]


def test_expired_lease_closes_verification_stream(tmp_path: Path) -> None:
    closed: list[bool] = []
    now = [0.0]

    class ExpiringSink(LocalArtifactSink):
        def read(self, blob: BlobIdentity) -> Iterator[bytes]:
            try:
                now[0] = 200
                yield b"x"
            finally:
                closed.append(True)

    def heartbeat() -> None:
        if now[0] >= 180:
            raise ArtifactError("artifact_checkpoint")

    sink = ExpiringSink(tmp_path)
    blob = hash_stream(io.BytesIO(b"x"))
    path = sink.root / blob.key
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    with pytest.raises(ArtifactError, match="artifact_checkpoint"):
        verify(sink, blob, progress=LeaseProgress(heartbeat, clock=lambda: now[0]))
    assert closed == [True]


def test_mutation_after_plan_precedes_every_remote_part(tmp_path: Path) -> None:
    data = b"expected"
    blob = hash_stream(io.BytesIO(data))
    source = io.BytesIO(data)

    class RacingSink(LocalArtifactSink):
        def begin(self, identity: BlobIdentity) -> str:
            upload_id = super().begin(identity)
            # A different worker finishes after our missing-object probe.
            target = self.root / identity.key
            target.parent.mkdir(parents=True)
            target.write_bytes(data)
            source.seek(0)
            source.write(b"modified")
            return upload_id

        def upload_part(
            self, identity: BlobIdentity, upload_id: str, number: int, part: bytes
        ) -> UploadedPart:
            raise AssertionError("changed source bytes reached remote part upload")

    sink = RacingSink(tmp_path)
    with pytest.raises(ArtifactError, match="artifact_integrity"):
        upload(
            sink=sink,
            source=source,
            blob=blob,
            upload_id=None,
            parts=(),
            checkpoint=lambda *_: None,
            assert_lease=lambda: None,
        )
    verify(sink, blob)
