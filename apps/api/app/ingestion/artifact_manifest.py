"""Durable artifact identities and leases, each operation in a short transaction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.ingestion.artifact_sink import ArtifactError, BlobIdentity, UploadedPart
from app.models import ArtifactBlob, ArtifactCopy, ArtifactReference, ArtifactRunSeal
from app.transactional_store import CollectionUnitOfWork, MutationLockTimeout

LEASE_SECONDS = 180


class ArtifactConflict(ArtifactError):
    def __init__(self) -> None:
        super().__init__("artifact_integrity")


class ArtifactLeaseLost(ArtifactError):
    def __init__(self) -> None:
        super().__init__("artifact_checkpoint")


@dataclass(frozen=True)
class UploadLease:
    blob_id: UUID
    sink_id: str
    token: UUID
    blob: BlobIdentity
    upload_id: str | None
    parts: tuple[UploadedPart, ...]
    audit: bool = False


def _now(session: Session) -> datetime:
    return cast(datetime, session.execute(select(func.clock_timestamp())).scalar_one())


def _lock_observation(session: Session, source_key: str, run_id: str) -> None:
    identity = json.dumps(["o01-artifact-observation-v1", source_key, run_id]).encode()
    key = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def public_source_url(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise ArtifactError("artifact_configuration") from None
    # Queries are omitted from public provenance to exclude signed URL/token
    # material. Connector identities may retain a separate private source query.
    if (
        len(value) > 4096
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ArtifactError("artifact_configuration")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


class ArtifactManifest:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @contextmanager
    def _transaction(self, *, canonical: bool = False) -> Iterator[Session]:
        try:
            with self.sessions.begin() as session:
                session.execute(text("SET LOCAL lock_timeout = '1500ms'"))
                session.execute(text("SET LOCAL statement_timeout = '5s'"))
                if canonical:
                    CollectionUnitOfWork(session).acquire_canonical_mutation_lock()
                yield session
        except (SQLAlchemyError, MutationLockTimeout):
            raise ArtifactError("artifact_unavailable") from None

    def reserve(
        self,
        *,
        blob: BlobIdentity,
        sink_id: str,
        source_key: str,
        run_id: str,
        artifact_type: str,
        logical_key: str,
        required: bool,
        content_type: str | None = None,
        source_url: str | None = None,
        parent_reference_id: UUID | None = None,
    ) -> UUID:
        for value, limit in (
            (source_key, 128),
            (run_id, 128),
            (artifact_type, 48),
            (logical_key, 256),
        ):
            if not value.strip() or len(value) > limit:
                raise ArtifactError("artifact_configuration")
        if content_type is not None and len(content_type) > 128:
            raise ArtifactError("artifact_configuration")
        source_url = public_source_url(source_url)
        with self._transaction() as session:
            _lock_observation(session, source_key, run_id)
            sealed = session.get(ArtifactRunSeal, (source_key, run_id))
            if sealed is not None:
                existing = session.scalar(
                    select(ArtifactReference.id).where(
                        ArtifactReference.source_key == source_key,
                        ArtifactReference.run_id == run_id,
                        ArtifactReference.artifact_type == artifact_type,
                        ArtifactReference.logical_key == logical_key,
                    )
                )
                if existing is None:
                    raise ArtifactConflict()
            session.execute(
                insert(ArtifactBlob)
                .values(
                    id=uuid4(),
                    sha256=blob.sha256,
                    byte_size=blob.byte_size,
                )
                .on_conflict_do_nothing(index_elements=["sha256"])
            )
            stored_blob = session.scalar(
                select(ArtifactBlob).where(ArtifactBlob.sha256 == blob.sha256)
            )
            assert stored_blob is not None
            if stored_blob.byte_size != blob.byte_size:
                raise ArtifactConflict()
            session.execute(
                insert(ArtifactCopy)
                .values(
                    blob_id=stored_blob.id,
                    sink_id=sink_id,
                    object_key=blob.key,
                    state="pending",
                )
                .on_conflict_do_nothing(index_elements=["blob_id", "sink_id"])
            )
            if parent_reference_id is not None:
                parent = session.get(ArtifactReference, parent_reference_id)
                if parent is None or (parent.source_key, parent.run_id) != (source_key, run_id):
                    raise ArtifactConflict()
                # References are immutable and parents must preexist. Therefore
                # adding this new child cannot introduce a self-reference/cycle.
            values = dict(
                source_key=source_key,
                run_id=run_id,
                artifact_type=artifact_type,
                logical_key=logical_key,
                blob_id=stored_blob.id,
                required=required,
                content_type=content_type,
                source_url=source_url,
                parent_reference_id=parent_reference_id,
            )
            session.execute(
                insert(ArtifactReference)
                .values(id=uuid4(), **values)
                .on_conflict_do_nothing(constraint="uq_artifact_reference_observation")
            )
            reference = session.scalar(
                select(ArtifactReference).where(
                    ArtifactReference.source_key == source_key,
                    ArtifactReference.run_id == run_id,
                    ArtifactReference.artifact_type == artifact_type,
                    ArtifactReference.logical_key == logical_key,
                )
            )
            assert reference is not None
            if any(getattr(reference, key) != value for key, value in values.items()):
                raise ArtifactConflict()
            return reference.id

    def claim(self, reference_id: UUID, sink_id: str, *, audit: bool = False) -> UploadLease | None:
        token = uuid4()
        with self._transaction(canonical=audit) as session:
            reference = session.get(ArtifactReference, reference_id)
            if reference is None:
                raise ArtifactError("artifact_missing")
            blob = session.get(ArtifactBlob, reference.blob_id)
            assert blob is not None
            condition = [] if audit else [ArtifactCopy.state != "verified"]
            row = session.scalar(
                update(ArtifactCopy)
                .where(
                    ArtifactCopy.blob_id == blob.id,
                    ArtifactCopy.sink_id == sink_id,
                    or_(
                        ArtifactCopy.lease_token.is_(None),
                        ArtifactCopy.lease_expires_at <= func.clock_timestamp(),
                    ),
                    or_(
                        ArtifactCopy.next_attempt_at.is_(None),
                        ArtifactCopy.next_attempt_at <= func.clock_timestamp(),
                    ),
                    *condition,
                )
                .values(
                    lease_token=token,
                    lease_expires_at=func.clock_timestamp() + timedelta(seconds=LEASE_SECONDS),
                    attempts=ArtifactCopy.attempts + 1,
                )
                .returning(ArtifactCopy)
            )
            if row is None:
                return None
            return UploadLease(
                blob.id,
                sink_id,
                token,
                BlobIdentity(blob.sha256, blob.byte_size),
                row.multipart_upload_id,
                tuple(UploadedPart(**part) for part in row.multipart_parts),
                audit,
            )

    def _leased(self, session: Session, lease: UploadLease) -> ArtifactCopy:
        row = session.scalar(
            select(ArtifactCopy)
            .where(
                ArtifactCopy.blob_id == lease.blob_id,
                ArtifactCopy.sink_id == lease.sink_id,
                ArtifactCopy.lease_token == lease.token,
                ArtifactCopy.lease_expires_at > func.clock_timestamp(),
            )
            .with_for_update()
        )
        if row is None or row.lease_expires_at is None or row.lease_expires_at <= _now(session):
            raise ArtifactLeaseLost()
        return row

    def heartbeat(self, lease: UploadLease) -> None:
        with self._transaction(canonical=lease.audit) as session:
            row = self._leased(session, lease)
            row.lease_expires_at = _now(session) + timedelta(seconds=LEASE_SECONDS)

    def lookup(self, reference_id: UUID, sink_id: str) -> tuple[BlobIdentity, str]:
        with self._transaction() as session:
            row = session.execute(
                select(ArtifactBlob, ArtifactCopy.state)
                .join(
                    ArtifactReference,
                    ArtifactReference.blob_id == ArtifactBlob.id,
                )
                .join(ArtifactCopy, ArtifactCopy.blob_id == ArtifactBlob.id)
                .where(
                    ArtifactReference.id == reference_id,
                    ArtifactCopy.sink_id == sink_id,
                )
            ).one_or_none()
            if row is None:
                raise ArtifactError("artifact_missing")
            return BlobIdentity(row.ArtifactBlob.sha256, row.ArtifactBlob.byte_size), row.state

    def uploaded(self, lease: UploadLease) -> None:
        with self._transaction() as session:
            row = self._leased(session, lease)
            row.state = "uploaded"
            row.uploaded_at = _now(session)

    def checkpoint(
        self,
        lease: UploadLease,
        upload_id: str,
        parts: tuple[UploadedPart, ...],
    ) -> None:
        if not 1 <= len(upload_id) <= 2048 or len(parts) > 1024:
            raise ArtifactError("artifact_checkpoint")
        with self._transaction(canonical=lease.audit) as session:
            row = self._leased(session, lease)
            row.multipart_upload_id = upload_id
            row.multipart_parts = [
                dict(
                    number=part.number,
                    etag=part.etag,
                    sha256=part.sha256,
                    byte_size=part.byte_size,
                )
                for part in parts
            ]

    def verified(self, lease: UploadLease) -> None:
        with self._transaction(canonical=lease.audit) as session:
            row = self._leased(session, lease)
            now = _now(session)
            row.state = "verified"
            row.uploaded_at = row.uploaded_at or now
            row.verified_at = now
            row.last_audit_at = now
            row.failure_code = None
            row.next_attempt_at = None
            row.lease_token = None
            row.lease_expires_at = None
            row.multipart_upload_id = None
            row.multipart_parts = []

    def failed(self, lease: UploadLease, error: ArtifactError) -> None:
        with self._transaction(canonical=lease.audit) as session:
            row = self._leased(session, lease)
            if row.state != "verified" or error.code in {"artifact_missing", "artifact_integrity"}:
                row.state = "failed"
            row.failure_code = error.code
            if error.code == "artifact_checkpoint":
                # NoSuchUpload (or another invalid checkpoint) cannot be resumed.
                # Keep the reference and retry budget, but start a new upload ID.
                row.multipart_upload_id = None
                row.multipart_parts = []
            row.next_attempt_at = _now(session) + timedelta(
                seconds=min(3600, 5 * 2 ** min(row.attempts, 10))
            )
            row.lease_token = None
            row.lease_expires_at = None


def require_verified_references(
    session: Session,
    *,
    reference_ids: tuple[UUID, ...],
    source_key: str,
    run_id: str,
    sink_id: str,
    allow_empty: bool = False,
) -> None:
    """Caller holds C02 lock; no object-store I/O or independent transaction here."""
    if (
        (not reference_ids and not allow_empty)
        or len(reference_ids) > 1024
        or len(set(reference_ids)) != len(reference_ids)
    ):
        raise ArtifactError("artifact_unavailable")
    _lock_observation(session, source_key, run_id)
    required_ids = set(
        session.scalars(
            select(ArtifactReference.id)
            .where(
                ArtifactReference.source_key == source_key,
                ArtifactReference.run_id == run_id,
                ArtifactReference.required.is_(True),
            )
            .limit(1025)
        ).all()
    )
    if required_ids != set(reference_ids):
        raise ArtifactError("artifact_unavailable")
    rows = session.execute(
        select(ArtifactReference, ArtifactCopy, ArtifactBlob)
        .join(
            ArtifactCopy,
            ArtifactCopy.blob_id == ArtifactReference.blob_id,
        )
        .join(ArtifactBlob, ArtifactBlob.id == ArtifactReference.blob_id)
        .where(
            ArtifactReference.id.in_(reference_ids),
            ArtifactReference.source_key == source_key,
            ArtifactReference.run_id == run_id,
            ArtifactReference.required.is_(True),
            ArtifactCopy.sink_id == sink_id,
        )
        .order_by(ArtifactCopy.blob_id)
        .with_for_update(of=ArtifactCopy)
    ).all()
    if len(rows) != len(reference_ids) or any(row.ArtifactCopy.state != "verified" for row in rows):
        raise ArtifactError("artifact_unavailable")
    digest = hashlib.sha256(
        json.dumps(
            sorted(
                (str(row.ArtifactReference.id), row.ArtifactBlob.sha256, row.ArtifactBlob.byte_size)
                for row in rows
            ),
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    sealed = session.get(ArtifactRunSeal, (source_key, run_id))
    if sealed is not None:
        if sealed.required_set_sha256 != digest or sealed.required_count != len(rows):
            raise ArtifactConflict()
    else:
        session.add(
            ArtifactRunSeal(
                source_key=source_key,
                run_id=run_id,
                required_set_sha256=digest,
                required_count=len(rows),
            )
        )
        session.flush()
