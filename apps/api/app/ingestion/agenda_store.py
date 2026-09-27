"""Revision-aware agenda merge using the C02 canonical mutation boundary.

PDF extraction and O01 uploads finish before this module is called. All reads used
to decide identity happen after acquiring the canonical transaction lock.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from app.config import get_settings
from app.ingestion.artifact_config import require_hosted_artifact_storage
from app.ingestion.artifact_sink import ArtifactError

SOURCE_KEY = "huntsville_planning_agendas"
FINGERPRINT_VERSION = 1
PARSER_VERSION = "agenda-text-v1"


class ArtifactAgendaUnitOfWork:
    """Single-writer item merges; file commits are atomic individually only."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, dict[str, Any]]] = {}
        self.dirty: set[str] = set()

    def _collection(self, name: str) -> dict[str, dict[str, Any]]:
        from app.phase3_store import _collection_item_id, _read_collection

        if name not in self.rows:
            self.rows[name] = {
                (
                    SOURCE_KEY if name == "agenda_health" else _collection_item_id(name, index, row)
                ): row
                for index, row in enumerate(_read_collection(name))
            }
        return self.rows[name]

    def get_phase3(self, name: str, key: str) -> dict[str, Any] | None:
        return copy.deepcopy(self._collection(name).get(key))

    def list_phase3(self, name: str) -> list[dict[str, Any]]:
        return copy.deepcopy(list(self._collection(name).values()))

    def upsert_phase3(self, name: str, key: str, value: dict[str, Any]) -> None:
        self._collection(name)[key] = copy.deepcopy(value)
        self.dirty.add(name)

    def delete_phase3(self, name: str, key: str) -> None:
        self._collection(name).pop(key, None)
        self.dirty.add(name)

    def list_processed(self, name: str) -> list[dict[str, Any]]:
        from app.processed_store import read_processed_list_result

        return read_processed_list_result(name).require_ready(collection=name)

    def get_processed(self, name: str, key: str) -> dict[str, Any] | None:
        return next(
            (row for row in self.list_processed(name) if str(row.get("public_id")) == key),
            None,
        )

    def commit(self) -> None:
        from app.phase3_store import _write_collection

        # Validation failures discard staged mutations. An interrupted commit
        # can still leave partial cross-file state; use PostgreSQL for hosting.
        for name in sorted(self.dirty):
            _write_collection(name, list(self.rows[name].values()))


@contextmanager
def _agenda_mutation() -> Iterator[Any]:
    from app.phase3_store import _use_transactional_postgres

    settings = get_settings()
    require_hosted_artifact_storage(settings)
    if _use_transactional_postgres():
        from app.db import SessionLocal
        from app.transactional_store import CollectionUnitOfWork

        with SessionLocal.begin() as session:
            with CollectionUnitOfWork(session).canonical_mutation() as uow:
                yield uow
    else:
        if settings.artifact_durability_required:
            raise ArtifactError("artifact_configuration")
        artifact_uow = ArtifactAgendaUnitOfWork()
        yield artifact_uow
        artifact_uow.commit()


class AgendaIdentityConflict(RuntimeError):
    """An ambiguous observation needs an audited operator decision."""


def _processed_public_records(uow: Any) -> list[dict[str, Any]]:
    """Read the configured source under the operational mutation boundary."""
    if get_settings().processed_store_backend == "postgres":
        return cast(list[dict[str, Any]], uow.list_processed("development_records"))
    from app.processed_store import read_processed_list_result

    return read_processed_list_result("development_records").require_ready(
        collection="development_records"
    )


def _processed_public_record(uow: Any, public_id: str) -> dict[str, Any] | None:
    if get_settings().processed_store_backend == "postgres":
        return cast(dict[str, Any] | None, uow.get_processed("development_records", public_id))
    return next(
        (row for row in _processed_public_records(uow) if str(row.get("public_id")) == public_id),
        None,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _immutable(uow: Any, collection: str, key: str, value: dict[str, Any]) -> None:
    previous = uow.get_phase3(collection, key)
    if previous is None:
        uow.upsert_phase3(collection, key, value)
    elif previous != value:
        raise AgendaIdentityConflict(f"immutable {collection} identity conflicted")


def _content(record: dict[str, Any], document_date: str | None) -> dict[str, Any]:
    source = record.get("source_payload") or {}
    return {
        "fingerprint_version": FINGERPRINT_VERSION,
        "title": " ".join(str(record["title"]).split()),
        "description": " ".join(str(record["description"]).split()),
        "development_type": record["development_type"],
        "source_status": record["source_status"],
        "normalized_status": record["normalized_status"],
        "document_date": document_date,
        "lot_count": source.get("lot_count"),
        "unit_count": source.get("unit_count"),
        "developer": source.get("developer"),
        "engineer": source.get("engineer"),
        "location_text": source.get("location"),
    }


def _existing_document(uow: Any, incoming: dict[str, Any]) -> tuple[str | None, bool]:
    """Exact URL/date alias only; a changed URL is not proof of identity."""
    alias_key = _digest([SOURCE_KEY, incoming.get("url"), incoming.get("document_date")])
    alias = uow.get_phase3("agenda_document_aliases", alias_key)
    if alias is not None:
        return str(alias["document_id"]), False
    existing = [
        doc
        for doc in uow.list_phase3("source_documents")
        if doc.get("url") == incoming.get("url")
        and doc.get("document_date") == incoming.get("document_date")
    ]
    if len(existing) > 1:
        raise AgendaIdentityConflict("document URL/date collision")
    if existing:
        return str(existing[0]["id"]), True
    # Same-date, different-URL documents are ambiguous until an operator links
    # the alias. This avoids inventing a second logical meeting on URL churn.
    same_date = [
        doc
        for doc in uow.list_phase3("source_documents")
        if incoming.get("document_date") and doc.get("document_date") == incoming["document_date"]
    ]
    same_url = [
        doc for doc in uow.list_phase3("source_documents") if doc.get("url") == incoming.get("url")
    ]
    checksum = incoming.get("sha256")
    dateless_checksum_match = (
        incoming.get("document_date") is None
        and isinstance(checksum, str)
        and bool(checksum)
        and any(
            row.get("sha256") == checksum
            for collection in ("source_documents", "agenda_document_revisions")
            for row in uow.list_phase3(collection)
        )
    )
    if same_date or same_url or dateless_checksum_match:
        return None, True
    return None, False


def _merge_document(
    uow: Any, incoming: dict[str, Any], run_id: str | None
) -> tuple[str | None, str | None]:
    document_id, ambiguous = _existing_document(uow, incoming)
    if document_id is None and ambiguous:
        key = _digest(
            [
                SOURCE_KEY,
                incoming.get("url"),
                incoming.get("document_date"),
                incoming.get("sha256"),
            ]
        )
        _immutable(
            uow,
            "agenda_unresolved_documents",
            key,
            {
                "id": key,
                "url": incoming.get("url"),
                "document_date": incoming.get("document_date"),
                "sha256": incoming.get("sha256"),
                "reason": "document_identity_ambiguous",
                "status": "identity_unresolved",
                "observation_revision": 1,
            },
        )
        return None, None
    document_id = document_id or f"agenda-doc-{uuid4().hex}"
    alias_key = _digest([SOURCE_KEY, incoming.get("url"), incoming.get("document_date")])
    _immutable(
        uow,
        "agenda_document_aliases",
        alias_key,
        {
            "id": alias_key,
            "document_id": document_id,
            "url": incoming.get("url"),
            "document_date": incoming.get("document_date"),
        },
    )
    revision_id = _digest(
        [
            document_id,
            incoming.get("sha256"),
            incoming.get("text_sha256"),
            incoming.get("extraction_status"),
            PARSER_VERSION,
        ]
    )
    revision = {
        "id": revision_id,
        "document_id": document_id,
        "sha256": incoming.get("sha256"),
        "text_sha256": incoming.get("text_sha256"),
        "extraction_status": incoming.get("extraction_status"),
        "pdf_reference_id": incoming.get("pdf_reference_id"),
        "text_reference_id": incoming.get("text_reference_id"),
        "source_url": incoming.get("url"),
        "parser_version": PARSER_VERSION,
    }
    # References identify a run, so the first verified observation establishes
    # immutable revision evidence; later runs have their own observation rows.
    previous = uow.get_phase3("agenda_document_revisions", revision_id)
    if previous is None:
        uow.upsert_phase3("agenda_document_revisions", revision_id, revision)
    else:
        for key in ("document_id", "sha256", "text_sha256", "extraction_status", "parser_version"):
            if previous.get(key) != revision[key]:
                raise AgendaIdentityConflict("document revision collision")
    run_key = _digest([revision_id, run_id or incoming.get("fetched_at")])
    _immutable(
        uow,
        "agenda_document_observations",
        run_key,
        {
            "id": run_key,
            "document_id": document_id,
            "document_revision_id": revision_id,
            "run_id": run_id,
            "fetched_at": incoming.get("fetched_at"),
            "pdf_reference_id": incoming.get("pdf_reference_id"),
            "text_reference_id": incoming.get("text_reference_id"),
        },
    )
    current = uow.get_phase3("source_documents", document_id)
    if previous is not None and current and current.get("revision_id") not in (None, revision_id):
        # A verified replay appends run evidence, without reactivating history.
        return document_id, revision_id
    document = copy.deepcopy(incoming)
    document["id"] = document_id
    document["revision_id"] = revision_id
    if current:
        document["first_seen_at"] = current.get("first_seen_at") or current.get("fetched_at")
    else:
        document["first_seen_at"] = incoming.get("fetched_at")
    uow.upsert_phase3("source_documents", document_id, document)
    return document_id, revision_id


def _merge_candidate(
    uow: Any,
    incoming: dict[str, Any],
    *,
    document_id: str,
    revision_id: str,
    document_date: str | None,
    legacy_ambiguous: bool = False,
) -> str | None:
    ordinal = incoming.get("observation_ordinal")
    occurrence_id = _digest([revision_id, PARSER_VERSION, ordinal])
    mapped = uow.get_phase3("agenda_observations", occurrence_id)
    if mapped is not None:
        candidate_id = mapped.get("candidate_id")
        if candidate_id is None:
            return None
        already_applied = mapped.get("applied_content_revision") is not None or (
            "applied_content_revision" not in mapped
            and any(
                row.get("candidate_id") == candidate_id
                and row.get("document_revision_id") == revision_id
                for row in uow.list_phase3("agenda_candidate_revisions")
            )
        )
        if already_applied:
            # Resolved mappings from older checkpoints have revision evidence
            # instead of this marker. Neither form may replay over a decision.
            return str(candidate_id)
    else:
        # First import of a document can adopt an exact legacy staged ID. A new
        # document revision with no authoritative item key cannot guess a match.
        legacy = uow.get_phase3("agenda_staged_records", str(incoming["id"]))
        prior_candidates = [
            row
            for row in uow.list_phase3("agenda_staged_records")
            if (row.get("source_payload") or {}).get("source_document_id") == document_id
            and (row.get("source_payload") or {}).get("document_revision_id") is not None
            and (row.get("source_payload") or {}).get("document_revision_id") != revision_id
        ]
        legacy_exact_first_import = (
            legacy is not None
            and not prior_candidates
            and legacy.get("content_fingerprint") is None
            and (legacy.get("source_payload") or {}).get("source_document_id") == document_id
            and (incoming.get("source_payload") or {}).get("source_document_id") == document_id
            and _content(legacy, document_date) == _content(incoming, document_date)
            and uow.get_phase3("agenda_candidate_revisions", f"{legacy['id']}:1") is None
        )
        if legacy_ambiguous:
            candidate_id = (
                None if legacy is not None or prior_candidates else f"stage-agenda-{uuid4().hex}"
            )
        elif prior_candidates:
            # Legacy adoption is limited to an exact first import. An existing
            # C04 candidate from another revision is never linked by title ID.
            candidate_id = str(legacy["id"]) if legacy_exact_first_import else None
        elif legacy is not None:
            candidate_id = str(legacy["id"]) if legacy_exact_first_import else None
        else:
            candidate_id = f"stage-agenda-{uuid4().hex}"
        observation = {
            "id": occurrence_id,
            "document_id": document_id,
            "document_revision_id": revision_id,
            "parser_version": PARSER_VERSION,
            "ordinal": ordinal,
            "source_excerpt": str(incoming.get("title", ""))[:200],
            "source_snapshot": copy.deepcopy(incoming),
            "document_date": document_date,
            "candidate_id": candidate_id,
            "status": "resolved" if candidate_id else "identity_unresolved",
            "observation_revision": 1,
            "applied_content_revision": None,
        }
        _immutable(uow, "agenda_observations", occurrence_id, observation)
        if candidate_id is None:
            return None
    assert candidate_id is not None
    current = uow.get_phase3("agenda_staged_records", str(candidate_id))
    fingerprint = _digest(_content(incoming, document_date))
    if current is not None:
        if current.get("review_status") not in (None, "pending") and not current.get("reviewed_at"):
            baseline_id = f"{candidate_id}:legacy-baseline"
            if uow.get_phase3("agenda_decision_events", baseline_id) is None:
                uow.upsert_phase3(
                    "agenda_decision_events",
                    baseline_id,
                    {
                        "id": baseline_id,
                        "candidate_id": candidate_id,
                        "content_revision": int(current.get("content_revision", 1)),
                        "previous_status": None,
                        "action": current["review_status"],
                        "notes": current.get("review_notes"),
                        "actor": current.get("review_actor") or "unknown_legacy",
                        "decided_at": current.get("reviewed_at"),
                        "state_revision": int(current.get("state_revision", 1)),
                        "baseline": True,
                    },
                )
        prior_fp = current.get("content_fingerprint") or _digest(_content(current, document_date))
        prior_content_revision = int(current.get("content_revision", 1))
        prior_version_id = f"{candidate_id}:{prior_content_revision}"
        if uow.get_phase3("agenda_candidate_revisions", prior_version_id) is None:
            uow.upsert_phase3(
                "agenda_candidate_revisions",
                prior_version_id,
                {
                    "id": prior_version_id,
                    "candidate_id": candidate_id,
                    "content_revision": prior_content_revision,
                    "content_fingerprint": prior_fp,
                    "fingerprint_version": FINGERPRINT_VERSION,
                    "document_revision_id": (current.get("source_payload") or {}).get(
                        "document_revision_id"
                    ),
                    "source_snapshot": copy.deepcopy(current),
                },
            )
        if prior_fp == fingerprint:
            if current.get("content_fingerprint") is None:
                current["content_fingerprint"] = fingerprint
                current["fingerprint_version"] = FINGERPRINT_VERSION
                current["content_revision"] = prior_content_revision
                current["state_revision"] = int(current.get("state_revision", 1))
                uow.upsert_phase3("agenda_staged_records", str(candidate_id), current)
            _mark_observation_applied(uow, occurrence_id, prior_content_revision)
            return str(candidate_id)
    content_revision = int(current.get("content_revision", 1)) + 1 if current else 1
    state_revision = int(current.get("state_revision", 0)) + 1 if current else 1
    record = copy.deepcopy(incoming)
    record["id"] = candidate_id
    record["content_revision"] = content_revision
    record["state_revision"] = state_revision
    record["content_fingerprint"] = fingerprint
    record["fingerprint_version"] = FINGERPRINT_VERSION
    record["review_status"] = "pending"
    record["review_notes"] = None
    record["source_payload"]["source_document_id"] = document_id
    record["source_payload"]["document_revision_id"] = revision_id
    if current:
        record["date_discovered"] = current["date_discovered"]
        record["publish_record"]["public_id"] = (current.get("publish_record") or {}).get(
            "public_id", f"hsv-agenda-{str(candidate_id).removeprefix('stage-agenda-')}"
        )
        record["publish_record"]["date_discovered"] = current["date_discovered"]
    else:
        record["publish_record"]["public_id"] = (
            f"hsv-agenda-{str(candidate_id).removeprefix('stage-agenda-')}"
        )
    record["publish_record"]["source_fields"]["source_document_id"] = document_id
    version_id = f"{candidate_id}:{content_revision}"
    _immutable(
        uow,
        "agenda_candidate_revisions",
        version_id,
        {
            "id": version_id,
            "candidate_id": candidate_id,
            "content_revision": content_revision,
            "content_fingerprint": fingerprint,
            "fingerprint_version": FINGERPRINT_VERSION,
            "document_revision_id": revision_id,
            "source_snapshot": copy.deepcopy(record),
        },
    )
    uow.upsert_phase3("agenda_staged_records", str(candidate_id), record)
    _mark_observation_applied(uow, occurrence_id, content_revision)
    return str(candidate_id)


def _mark_observation_applied(uow: Any, occurrence_id: str, content_revision: int) -> None:
    observation = uow.get_phase3("agenda_observations", occurrence_id)
    assert observation is not None
    observation["applied_content_revision"] = content_revision
    uow.upsert_phase3("agenda_observations", occurrence_id, observation)


def merge_agenda_artifacts(
    *,
    source_documents: list[dict[str, Any]],
    staged_records: list[dict[str, Any]],
    health: dict[str, Any],
    run_id: str | None = None,
    artifact_sink_id: str | None = None,
    required_reference_ids: tuple[UUID, ...] = (),
) -> dict[str, Any]:
    """Append immutable evidence and merge only affected agenda items atomically."""
    settings = get_settings()
    require_hosted_artifact_storage(settings)
    from app.phase3_store import _use_transactional_postgres

    if not _use_transactional_postgres():
        with _agenda_mutation() as uow:
            return _merge_agenda_batch(uow, source_documents, staged_records, health, run_id)
    from app.db import SessionLocal
    from app.ingestion.artifact_manifest import require_verified_references
    from app.models import ArtifactBlob, ArtifactReference
    from app.transactional_store import CollectionUnitOfWork

    if settings.artifact_durability_required and (not run_id or not artifact_sink_id):
        raise ArtifactError("artifact_unavailable")
    with SessionLocal.begin() as session:
        with CollectionUnitOfWork(session).canonical_mutation() as uow:
            if settings.artifact_durability_required:
                assert run_id is not None and artifact_sink_id is not None
                require_verified_references(
                    session,
                    reference_ids=required_reference_ids,
                    source_key=SOURCE_KEY,
                    run_id=run_id,
                    sink_id=artifact_sink_id,
                )
                expected_ids = {
                    UUID(str(reference))
                    for document in source_documents
                    for reference in (
                        document.get("pdf_reference_id"),
                        document.get("text_reference_id"),
                    )
                    if reference is not None
                }
                if expected_ids != set(required_reference_ids) or len(expected_ids) != 2 * len(
                    source_documents
                ):
                    raise ArtifactError("artifact_unavailable")
                for document in source_documents:
                    pdf = session.get(ArtifactReference, UUID(str(document["pdf_reference_id"])))
                    text = session.get(ArtifactReference, UUID(str(document["text_reference_id"])))
                    if pdf is None or text is None:
                        raise ArtifactError("artifact_unavailable")
                    pdf_blob = session.get(ArtifactBlob, pdf.blob_id)
                    text_blob = session.get(ArtifactBlob, text.blob_id)
                    if (
                        pdf.artifact_type != "source_pdf"
                        or text.artifact_type != "extracted_text"
                        or text.parent_reference_id != pdf.id
                        or pdf_blob is None
                        or text_blob is None
                        or pdf_blob.sha256 != document.get("sha256")
                        or text_blob.sha256 != document.get("text_sha256")
                    ):
                        raise ArtifactError("artifact_integrity")
            return _merge_agenda_batch(uow, source_documents, staged_records, health, run_id)


def _merge_agenda_batch(
    uow: Any,
    source_documents: list[dict[str, Any]],
    staged_records: list[dict[str, Any]],
    health: dict[str, Any],
    run_id: str | None,
) -> dict[str, Any]:
    by_legacy_document: dict[str, list[dict[str, Any]]] = {}
    health_out = copy.deepcopy(health)
    legacy_counts: dict[str, int] = {}
    for record in staged_records:
        by_legacy_document.setdefault(
            str((record.get("source_payload") or {}).get("source_document_id")), []
        ).append(record)
        legacy_id = str(record["id"])
        legacy_counts[legacy_id] = legacy_counts.get(legacy_id, 0) + 1
    affected: set[str] = set()
    for document in source_documents:
        document_id, revision_id = _merge_document(uow, document, run_id)
        if document_id is None or revision_id is None:
            continue
        for record in by_legacy_document.get(str(document["id"]), []):
            candidate_id = _merge_candidate(
                uow,
                record,
                document_id=document_id,
                revision_id=revision_id,
                document_date=document.get("document_date"),
                legacy_ambiguous=legacy_counts[str(record["id"])] > 1,
            )
            if candidate_id:
                affected.add(candidate_id)
    _refresh_duplicate_suggestions(uow, affected)
    return _persist_agenda_health(uow, health_out)


def _refresh_duplicate_suggestions(uow: Any, affected: set[str]) -> None:
    from app.phase3_store import _stable_id, build_duplicate_candidates

    def system_suggestion(row: dict[str, Any]) -> bool:
        return (
            row.get("generated_by") in (None, "agenda_matcher")
            and row.get("origin") in (None, "system")
            and row.get("id")
            == _stable_id("duplicate", row.get("staged_record_id"), row.get("candidate_public_id"))
            and not any(
                row.get(key)
                for key in (
                    "review_status",
                    "decision",
                    "resolution",
                    "review_actor",
                    "reviewed_at",
                    "manually_created",
                    "review_notes",
                    "notes",
                    "resolved_at",
                    "resolution_actor",
                )
            )
        )

    existing = uow.list_phase3("duplicate_candidates")
    protected = {str(row["id"]) for row in existing if not system_suggestion(row)}
    for row in existing:
        if str(row.get("staged_record_id")) in affected and system_suggestion(row):
            uow.delete_phase3("duplicate_candidates", str(row["id"]))
    published_by_id = {str(row["public_id"]): row for row in _processed_public_records(uow)}
    published_by_id.update(
        {str(row["public_id"]): row for row in uow.list_phase3("development_records")}
    )
    candidates = [
        row for row in uow.list_phase3("agenda_staged_records") if str(row.get("id")) in affected
    ]
    for candidate in build_duplicate_candidates(candidates, list(published_by_id.values())):
        if str(candidate["id"]) not in protected:
            uow.upsert_phase3(
                "duplicate_candidates",
                str(candidate["id"]),
                {
                    **candidate,
                    "generated_by": "agenda_matcher",
                },
            )


def _persist_agenda_health(uow: Any, health: dict[str, Any]) -> dict[str, Any]:
    health_out = copy.deepcopy(health)
    previous = uow.get_phase3("agenda_health", SOURCE_KEY) or {}
    health_out["last_attempt_at"] = health_out.get("checked_at")
    health_out["last_success_at"] = previous.get("last_success_at") or (
        previous.get("checked_at") if previous.get("status") == "healthy" else None
    )
    unresolved_count = sum(
        row.get("status") == "identity_unresolved"
        for name in ("agenda_unresolved_documents", "agenda_observations")
        for row in uow.list_phase3(name)
    )
    health_out["identity_unresolved_count"] = unresolved_count
    if unresolved_count:
        health_out["status"] = "degraded"
        health_out["identity_unresolved_count"] = unresolved_count
        errors = list(health_out.get("validation_errors") or [])
        errors.append("agenda_identity_unresolved")
        health_out["validation_errors"] = errors
        health_out["error_count"] = len(errors)
    elif health_out.get("status") == "healthy":
        health_out["last_success_at"] = health_out.get("checked_at")
    uow.upsert_phase3("agenda_health", SOURCE_KEY, health_out)
    return health_out


def persist_agenda_health(health: dict[str, Any]) -> dict[str, Any]:
    """Persist a failed discovery attempt without activating document/artifact state."""
    with _agenda_mutation() as uow:
        return _persist_agenda_health(uow, health)


class AgendaRevisionConflict(RuntimeError):
    """Expected state changed while the reviewer was working."""


class AgendaPublicationPending(RuntimeError):
    """A changed public snapshot needs C06's versioned publication path."""


def list_unresolved_documents() -> list[dict[str, Any]]:
    from app.phase3_store import _read_collection

    return [
        {
            "id": row["id"],
            "url": row["url"],
            "document_date": row.get("document_date"),
            "sha256": row["sha256"],
            "observation_revision": row["observation_revision"],
        }
        for row in _read_collection("agenda_unresolved_documents")
        if row.get("status") == "identity_unresolved"
    ]


def resolve_agenda_document_alias(
    observation_id: str,
    *,
    document_id: str | None,
    expected_observation_revision: int,
    actor: str,
    reason: str,
) -> dict[str, Any] | None:
    """Link a new URL to a document or explicitly create a separate one.

    The stored source observation is not activated by this command; a later
    verified ingestion retries with the newly recorded alias.
    """
    if not reason.strip():
        raise ValueError("A resolution reason is required")

    with _agenda_mutation() as uow:
        observation = uow.get_phase3("agenda_unresolved_documents", observation_id)
        if observation is None:
            return None
        if observation.get("status") != "identity_unresolved" or (
            observation["observation_revision"] != expected_observation_revision
        ):
            raise AgendaRevisionConflict("document observation changed")
        if document_id is not None and uow.get_phase3("source_documents", document_id) is None:
            raise AgendaIdentityConflict("logical document does not exist")
        resolved_id = document_id or f"agenda-doc-{uuid4().hex}"
        alias_key = _digest([SOURCE_KEY, observation["url"], observation.get("document_date")])
        _immutable(
            uow,
            "agenda_document_aliases",
            alias_key,
            {
                "id": alias_key,
                "document_id": resolved_id,
                "url": observation["url"],
                "document_date": observation.get("document_date"),
            },
        )
        observation["status"] = "resolved"
        observation["observation_revision"] += 1
        observation["document_id"] = resolved_id
        uow.upsert_phase3("agenda_unresolved_documents", observation_id, observation)
        event_id = f"document:{observation_id}:{observation['observation_revision']}"
        _immutable(
            uow,
            "agenda_identity_resolutions",
            event_id,
            {
                "id": event_id,
                "observation_id": observation_id,
                "document_id": resolved_id,
                "action": "link" if document_id else "create",
                "actor": actor,
                "reason": reason.strip(),
                "expected_observation_revision": expected_observation_revision,
                "resolved_at": datetime.now(UTC).isoformat(),
            },
        )
        return cast(dict[str, Any], observation)


def list_unresolved_observations() -> list[dict[str, Any]]:
    from app.phase3_store import _read_collection

    return [
        {
            "id": row["id"],
            "document_id": row["document_id"],
            "document_revision_id": row["document_revision_id"],
            "source_excerpt": row["source_excerpt"],
            "observation_revision": row["observation_revision"],
        }
        for row in _read_collection("agenda_observations")
        if row.get("status") == "identity_unresolved"
    ]


def resolve_agenda_observation(
    observation_id: str,
    *,
    candidate_id: str | None,
    expected_observation_revision: int,
    expected_candidate_revision: int | None,
    actor: str,
    reason: str,
) -> dict[str, Any] | None:
    """Audit a link or explicit new-candidate decision; never match mutable text."""
    if not reason.strip():
        raise ValueError("A resolution reason is required")

    with _agenda_mutation() as uow:
        observation = uow.get_phase3("agenda_observations", observation_id)
        if observation is None:
            return None
        if observation["status"] != "identity_unresolved" or (
            int(observation["observation_revision"]) != expected_observation_revision
        ):
            raise AgendaRevisionConflict("agenda observation changed")
        current = (
            uow.get_phase3("agenda_staged_records", candidate_id)
            if candidate_id is not None
            else None
        )
        if candidate_id is not None and current is None:
            raise AgendaIdentityConflict("candidate does not exist")
        if (
            current is not None
            and (current.get("source_payload") or {}).get("source_document_id")
            != observation["document_id"]
        ):
            raise AgendaIdentityConflict("candidate belongs to a different document")
        if (
            current is not None
            and int(current.get("state_revision", 0)) != expected_candidate_revision
        ):
            raise AgendaRevisionConflict("candidate changed")
        if candidate_id is None and expected_candidate_revision is not None:
            raise AgendaRevisionConflict("new candidate has no prior revision")
        resolved_id = candidate_id or f"stage-agenda-{uuid4().hex}"
        observation["candidate_id"] = resolved_id
        observation["applied_content_revision"] = None
        observation["status"] = "resolved"
        observation["observation_revision"] += 1
        uow.upsert_phase3("agenda_observations", observation_id, observation)
        event_id = f"{observation_id}:{observation['observation_revision']}"
        _immutable(
            uow,
            "agenda_identity_resolutions",
            event_id,
            {
                "id": event_id,
                "observation_id": observation_id,
                "candidate_id": resolved_id,
                "action": "link" if candidate_id else "create",
                "actor": actor,
                "reason": reason.strip(),
                "expected_observation_revision": expected_observation_revision,
                "expected_candidate_revision": expected_candidate_revision,
                "resolved_at": datetime.now(UTC).isoformat(),
            },
        )
        return_id = _merge_candidate(
            uow,
            observation["source_snapshot"],
            document_id=observation["document_id"],
            revision_id=observation["document_revision_id"],
            document_date=observation.get("document_date"),
        )
        assert return_id == resolved_id
        result = uow.get_phase3("agenda_staged_records", resolved_id)
        assert result is not None
        if current is not None and result["state_revision"] == current["state_revision"]:
            result["state_revision"] += 1
            uow.upsert_phase3("agenda_staged_records", resolved_id, result)
        _refresh_duplicate_suggestions(uow, {resolved_id})
        return cast(dict[str, Any], result)


def review_agenda_candidate(
    staged_id: str,
    *,
    action: str,
    notes: str | None,
    expected_revision: int | None,
    actor: str = "reviewer",
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    """Review and optional first publication commit together with state history."""
    from datetime import UTC, datetime

    from app.ingestion.source_merge import public_fingerprint
    from app.public_fields import public_source_fields
    from app.public_geometry import require_publishable_geometry

    with _agenda_mutation() as uow:
        record = uow.get_phase3("agenda_staged_records", staged_id)
        if record is None:
            return None
        if expected_revision is None or expected_revision != int(record.get("state_revision", 0)):
            raise AgendaRevisionConflict("agenda decision revision changed")
        published: dict[str, Any] | None = None
        if action == "approved":
            require_publishable_geometry(record)
            published = copy.deepcopy(record["publish_record"])
            # A reviewer geometry correction may be stored on the staged row.
            published["geometry"] = copy.deepcopy(record["geometry"])
            published["centroid"] = record.get("centroid") or _point_centroid(record["geometry"])
            published["geometry_source"] = record["geometry_source"]
            published["geometry_confidence"] = record["geometry_confidence"]
            require_publishable_geometry(published)
            published["source_fields"] = public_source_fields(published.get("source_fields", {}))
            published["review_status"] = "published"
            published["date_last_checked"] = datetime.now(UTC).date().isoformat()
            public_id = str(published["public_id"])
            operational_public = uow.get_phase3("development_records", public_id)
            processed_public = _processed_public_record(uow, public_id)
            if operational_public is not None and processed_public is not None:
                raise AgendaIdentityConflict("public record has ambiguous store ownership")
            existing_public = operational_public or processed_public
            if existing_public is not None:
                if public_fingerprint(existing_public) != public_fingerprint(published):
                    raise AgendaPublicationPending(
                        "changed agenda publication requires versioned update"
                    )
                published = existing_public
            else:
                uow.upsert_phase3("development_records", public_id, published)
                version_id = f"version-{public_id}-1"
                uow.upsert_phase3(
                    "record_versions",
                    version_id,
                    {
                        "id": version_id,
                        "public_id": public_id,
                        "version_number": 1,
                        "changed_at": datetime.now(UTC).isoformat(),
                        "changed_by": actor,
                        "change_type": "published",
                        "snapshot": copy.deepcopy(published),
                    },
                )
                change_id = f"change-{public_id}-published"
                uow.upsert_phase3(
                    "change_log",
                    change_id,
                    {
                        "id": change_id,
                        "public_id": public_id,
                        "title": published["title"],
                        "changed_at": datetime.now(UTC).isoformat(),
                        "change_type": "published",
                        "summary": (
                            f"{published['title']} was published from a reviewer-gated source."
                        ),
                    },
                )
        elif action not in {"rejected", "needs_info"}:
            raise ValueError("Unsupported agenda review action")
        previous_status = record["review_status"]
        record["review_status"] = action
        record["review_notes"] = notes
        record["review_actor"] = actor
        record["reviewed_at"] = datetime.now(UTC).isoformat()
        record["state_revision"] = expected_revision + 1
        uow.upsert_phase3("agenda_staged_records", staged_id, record)
        event_id = f"{staged_id}:{record['state_revision']}"
        _immutable(
            uow,
            "agenda_decision_events",
            event_id,
            {
                "id": event_id,
                "candidate_id": staged_id,
                "content_revision": record["content_revision"],
                "previous_status": previous_status,
                "action": action,
                "notes": notes,
                "actor": actor,
                "decided_at": record["reviewed_at"],
                "state_revision": record["state_revision"],
            },
        )
        return record, published


def _point_centroid(geometry: dict[str, Any]) -> list[float] | None:
    if geometry.get("type") == "Point":
        coordinates = geometry.get("coordinates")
        if isinstance(coordinates, list) and len(coordinates) == 2:
            return coordinates
    from shapely.geometry import shape

    center = shape(geometry).centroid
    return [float(center.x), float(center.y)]
