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
    checked_at: datetime
    records: tuple[SourceRecord, ...]
    # Legacy callers did not have a reliable scoped-count contract.  Omitting
    # coverage must therefore be conservative, rather than accidentally
    # treating a successful transport as a complete observation.
    coverage: Coverage | None = None
    outcome: Literal["success", "failed"] = "success"
    quarantined_count: int = 0


class CanonicalPublicationWriter:
    """The C06 event hook seam; C03 only writes the current canonical item."""

    def __init__(self, unit_of_work: CollectionUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def upsert(
        self,
        *,
        before: dict[str, Any] | None,
        after: dict[str, Any],
        source_key: str,
        run_id: str,
    ) -> None:
        # C06 will consume the complete before/after/provenance seam to create
        # publication events in this same transaction.  Keep the arguments now
        # so source merges cannot bypass that future hook.
        del before, source_key, run_id
        self.unit_of_work.upsert_processed("development_records", str(after["public_id"]), after)


class RegistryInitializationRequired(RuntimeError):
    """Existing source rows need an audited backfill before creating new anchors."""


def merge_postgres_batch(
    session: Session,
    batch: SourceBatch,
    *,
    unit_of_work: CollectionUnitOfWork | None = None,
) -> dict[str, int | bool]:
    """Merge a pre-parsed source batch in one C02 lock/transaction.

    Network, parsing and geometry validation must finish before this entry point.
    """
    unit = unit_of_work or CollectionUnitOfWork(session)
    if unit_of_work is None:
        with unit.canonical_mutation():
            return _merge_locked(session, unit, batch)
    return _merge_locked(session, unit, batch)


def _merge_locked(
    session: Session,
    unit_of_work: CollectionUnitOfWork,
    batch: SourceBatch,
) -> dict[str, int | bool]:
    """Merge after the caller has acquired the shared C02 mutation lock."""
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

    if batch.outcome == "failed":
        effective_coverage: Coverage = "failed"
    elif batch.quarantined_count:
        effective_coverage = "partial"
    else:
        effective_coverage = batch.coverage or "unknown"
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
                        f"{batch.source_key} has unresolved canonical rows without a registry "
                        "anchor; "
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
        after["source_key"] = batch.source_key
        after["source_record_id"] = input_record.source_record_id
        after["date_discovered"] = _discovery_date(before, registry)
        after["content_fingerprint"] = public_fingerprint(after)
        after["content_fingerprint_version"] = FINGERPRINT_VERSION
        publication.upsert(
            before=before,
            after=after,
            source_key=batch.source_key,
            run_id=batch.run_id,
        )
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
    """Hash meaningful public content without replacing the stored source geometry.

    This has deliberately narrow provenance attributes.  The canonical record may
    retain a larger reviewer/audit payload, but adding an arbitrary raw property
    must not make ingestion churn public revisions.
    """
    allowed = {
        key: record.get(key)
        for key in (
            "public_id",
            "source_key",
            "source_record_id",
            "title",
            "description",
            "development_type",
            "status",
            "source_status",
            "source_url",
            "source_agency",
            "date_discovered",
            "application_date",
            "approval_date",
            "permit_issue_date",
            "geometry_source",
            "geometry_confidence",
            "confidence_level",
        )
    }
    allowed["geometry"] = _canonical_geometry(record.get("geometry"))
    allowed["proximity_flags"] = _unordered_collection(record.get("proximity_flags"))
    allowed["source_fields"] = _allowed_source_fields(record.get("source_fields"))
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


PUBLIC_SOURCE_FIELD_NAMES = frozenset(
    {
        "SubdID",
        "Subdivision",
        "Phase",
        "Status",
        "HousingUnits",
        "HousingUnitType",
        "Layout_date",
        "Prelim_date",
        "Final_date",
        "AsBuilt_date",
        "PermitID",
        "Permit_Issue_DateTime",
        "OccupancyType",
        "OccupancySubtype",
        "TypeOfWork",
        "NumberOfUnits",
        "Subd_ID",
        "Subd_Name",
        "Subd_Type",
        "Parcels",
        "Book",
        "Page",
        "DocNum",
        "YearFiled",
        "DateFiled",
    }
)


def _allowed_source_fields(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: _canonical(value[key])
        for key in sorted(value)
        if key in PUBLIC_SOURCE_FIELD_NAMES
    }


def _unordered_collection(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    canonical = [_canonical(item) for item in value]
    return sorted(
        canonical,
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
    )


def _canonical_geometry(value: Any) -> Any:
    """Normalize only the fingerprint representation of equivalent GeoJSON rings."""
    if not isinstance(value, dict):
        return _canonical(value)
    geometry_type = value.get("type")
    coordinates = value.get("coordinates")
    if geometry_type == "Polygon" and isinstance(coordinates, list):
        return {"type": geometry_type, "coordinates": _canonical_polygon(coordinates)}
    if geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        polygons = [_canonical_polygon(polygon) for polygon in coordinates if isinstance(polygon, list)]
        return {
            "type": geometry_type,
            "coordinates": sorted(polygons, key=_json_sort_key),
        }
    return _canonical(value)


def _canonical_polygon(rings: list[Any]) -> list[Any]:
    normalized = [_canonical_ring(ring, clockwise=index > 0) for index, ring in enumerate(rings)]
    if not normalized:
        return []
    return [normalized[0], *sorted(normalized[1:], key=_json_sort_key)]


def _canonical_ring(value: Any, *, clockwise: bool) -> Any:
    if not isinstance(value, list) or not value:
        return _canonical(value)
    # Rings are closed in valid GeoJSON.  Preserve every coordinate exactly while
    # making a rotated/reversed representation compare equivalently for the hash.
    points = [_canonical(point) for point in value]
    body = points[:-1] if len(points) > 1 and points[0] == points[-1] else points
    if not body or any(not isinstance(point, list) or len(point) < 2 for point in body):
        return points
    area = sum(
        float(body[index][0]) * float(body[(index + 1) % len(body)][1])
        - float(body[(index + 1) % len(body)][0]) * float(body[index][1])
        for index in range(len(body))
    )
    should_reverse = area > 0 if clockwise else area < 0
    if should_reverse:
        body.reverse()
    start = min(range(len(body)), key=lambda index: _json_sort_key(body[index]))
    rotated = [*body[start:], *body[:start]]
    return [*rotated, copy.deepcopy(rotated[0])]


def _json_sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _discovery_date(before: dict[str, Any] | None, registry: SourceIdentityRegistry) -> str:
    if before is not None and isinstance(before.get("date_discovered"), str):
        return str(before["date_discovered"])
    return registry.first_discovered_at.date().isoformat()
