"""Locked, source-aware canonical batch merge for PostgreSQL ingestion."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SourceIdentityRegistry, SourceIngestionBatch, SourceObservation
from app.transactional_store import CollectionUnitOfWork

Coverage = Literal["complete", "partial", "failed", "unknown"]
FINGERPRINT_VERSION = "c03-public-v1"


@dataclass(frozen=True)
class SourceRecord:
    source_record_id: str
    provisional_public_id: str
    published: dict[str, Any]
    staged: dict[str, Any]


@dataclass(frozen=True)
class SourceBatch:
    run_id: str
    source_key: str
    scope_id: str
    scope_version: str
    coverage: Coverage
    outcome: Literal["success", "failed"]
    checked_at: datetime
    records: tuple[SourceRecord, ...]
    quarantined_count: int = 0


class CanonicalPublicationWriter:
    """The C06 event hook seam; C03 only writes the current canonical item."""

    def __init__(self, unit_of_work: CollectionUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def upsert(self, *, before: dict[str, Any] | None, after: dict[str, Any]) -> None:
        del before  # C06 consumes before/after here when it introduces publication events.
        self.unit_of_work.upsert_processed("development_records", str(after["public_id"]), after)


class RegistryInitializationRequired(RuntimeError):
    """Existing source rows need an audited backfill before creating new anchors."""


def merge_postgres_batch(session: Session, batch: SourceBatch) -> dict[str, int | bool]:
    """Merge a pre-parsed source batch in one C02 lock/transaction.

    Network, parsing and geometry validation must finish before this entry point.
    """
    unit_of_work = CollectionUnitOfWork(session)
    with unit_of_work.canonical_mutation():
        existing_batch = session.scalar(
            select(SourceIngestionBatch).where(
                SourceIngestionBatch.run_id == batch.run_id,
                SourceIngestionBatch.source_key == batch.source_key,
                SourceIngestionBatch.scope_id == batch.scope_id,
                SourceIngestionBatch.scope_version == batch.scope_version,
            )
        )
        if existing_batch is not None:
            return {"replayed": True, "observed": 0, "source_missing": 0}

        effective_coverage = "partial" if batch.quarantined_count else batch.coverage
        persisted_batch = SourceIngestionBatch(
            run_id=batch.run_id,
            source_key=batch.source_key,
            scope_id=batch.scope_id,
            scope_version=batch.scope_version,
            coverage=effective_coverage,
            outcome=batch.outcome,
            counts_json={"received": len(batch.records), "observed": 0, "source_missing": 0},
            finished_at=batch.checked_at,
        )
        session.add(persisted_batch)
        session.flush()
        current = {
            item["public_id"]: item
            for item in unit_of_work.list_processed("development_records")
        }
        registered_public_ids = set(
            session.scalars(
                select(SourceIdentityRegistry.public_id).where(
                    SourceIdentityRegistry.source_key == batch.source_key
                )
            ).all()
        )
        publication = CanonicalPublicationWriter(unit_of_work)
        observed_registry_ids: set[int] = set()
        for input_record in batch.records:
            registry = session.scalar(
                select(SourceIdentityRegistry).where(
                    SourceIdentityRegistry.source_key == batch.source_key,
                    SourceIdentityRegistry.source_record_id == input_record.source_record_id,
                )
            )
            if registry is None:
                if any(
                    record.get("source_url") == input_record.published.get("source_url")
                    and record.get("public_id") not in registered_public_ids
                    for record in current.values()
                ):
                    raise RegistryInitializationRequired(
                        f"{batch.source_key} has unresolved canonical rows without a registry anchor; "
                        "run the dry-run backfill and resolve its diagnostics first"
                    )
                registry = SourceIdentityRegistry(
                    source_key=batch.source_key,
                    source_record_id=input_record.source_record_id,
                    public_id=input_record.provisional_public_id,
                    first_discovered_at=batch.checked_at,
                    last_observed_at=batch.checked_at,
                )
                session.add(registry)
                session.flush()
            else:
                registry.last_observed_at = batch.checked_at
            observed_registry_ids.add(registry.id)
            before = current.get(registry.public_id)
            after = copy.deepcopy(input_record.published)
            after["public_id"] = registry.public_id
            after["date_discovered"] = _discovery_date(before, registry)
            after["content_fingerprint"] = public_fingerprint(after)
            after["content_fingerprint_version"] = FINGERPRINT_VERSION
            publication.upsert(before=before, after=after)
            staged = copy.deepcopy(input_record.staged)
            staged["id"] = f"stage-{registry.public_id}"
            staged["raw_record_id"] = input_record.source_record_id
            unit_of_work.upsert_processed("staged_development_records", staged["id"], staged)
            session.add(
                SourceObservation(
                    batch_id=persisted_batch.id,
                    registry_id=registry.id,
                    state="observed",
                    content_fingerprint=after["content_fingerprint"],
                    fingerprint_version=FINGERPRINT_VERSION,
                    observed_at=batch.checked_at,
                )
            )

        missing = 0
        if batch.outcome == "success" and effective_coverage == "complete":
            scoped_registry_ids = set(
                session.scalars(
                    select(SourceObservation.registry_id)
                    .join(
                        SourceIngestionBatch,
                        SourceObservation.batch_id == SourceIngestionBatch.id,
                    )
                    .where(
                        SourceIngestionBatch.source_key == batch.source_key,
                        SourceIngestionBatch.scope_id == batch.scope_id,
                        SourceIngestionBatch.scope_version == batch.scope_version,
                        SourceObservation.state == "observed",
                    )
                ).all()
            )
            for registry_id in scoped_registry_ids - observed_registry_ids:
                session.add(
                    SourceObservation(
                        batch_id=persisted_batch.id,
                        registry_id=registry_id,
                        state="source_missing",
                        observed_at=batch.checked_at,
                    )
                )
                missing += 1
        persisted_batch.counts_json = {
            "received": len(batch.records),
            "quarantined": batch.quarantined_count,
            "coverage": effective_coverage,
            "observed": len(observed_registry_ids),
            "source_missing": missing,
        }
        return {
            "replayed": False,
            "observed": len(observed_registry_ids),
            "source_missing": missing,
        }


def public_fingerprint(record: dict[str, Any]) -> str:
    allowed = {
        key: record.get(key)
        for key in (
            "public_id", "title", "description", "development_type", "status", "source_status",
            "source_url", "source_agency", "date_discovered", "application_date", "approval_date",
            "permit_issue_date", "geometry", "geometry_source", "geometry_confidence",
            "confidence_level", "proximity_flags",
        )
    }
    encoded = json.dumps(
        _canonical(allowed), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _discovery_date(before: dict[str, Any] | None, registry: SourceIdentityRegistry) -> str:
    if before is not None and isinstance(before.get("date_discovered"), str):
        return before["date_discovered"]
    return registry.first_discovered_at.date().isoformat()
