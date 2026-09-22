"""Audited migration of existing canonical rows to stable source anchors.

The service intentionally does not inspect titles, geometry, or other mutable
content.  Operators review the dry-run digest before applying it to a copied
database, then apply that exact report while holding the normal canonical lock.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.identity import SOURCE_ID_FIELDS, SourceIdentityError, source_record_id
from app.ingestion.sources.huntsville import BUILDING_PERMITS, NEW_SUBDIVISIONS
from app.ingestion.sources.madison_county import MADISON_COUNTY_SUBDIVISIONS
from app.models import SourceIdentityRegistry
from app.transactional_store import CollectionUnitOfWork

SOURCE_URLS = {
    NEW_SUBDIVISIONS.layer_url: NEW_SUBDIVISIONS.key,
    BUILDING_PERMITS.layer_url: BUILDING_PERMITS.key,
    MADISON_COUNTY_SUBDIVISIONS.layer_url: MADISON_COUNTY_SUBDIVISIONS.key,
}


def dry_run_source_identity_backfill(session: Session) -> dict[str, Any]:
    """Return deterministic candidates and diagnostics without changing database state."""
    unit = CollectionUnitOfWork(session)
    records = unit.list_processed("development_records")
    candidates: list[dict[str, str]] = []
    diagnostics: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    by_anchor: dict[tuple[str, str], list[str]] = {}
    records_by_public_id: dict[str, dict[str, Any]] = {}
    public_id_counts: dict[str, int] = {}
    for record in records:
        public_id = record.get("public_id")
        if isinstance(public_id, str) and public_id:
            public_id_counts[public_id] = public_id_counts.get(public_id, 0) + 1
    duplicate_public_ids = {public_id for public_id, count in public_id_counts.items() if count > 1}
    registered = {
        (row.source_key, row.source_record_id): row.public_id
        for row in session.scalars(select(SourceIdentityRegistry)).all()
    }

    for record in records:
        public_id = record.get("public_id")
        if not isinstance(public_id, str) or not public_id:
            diagnostics.append({"code": "invalid_public_id", "public_id": repr(public_id)})
            continue
        source_key = _source_key(record)
        if source_key is None:
            # Agenda/manual rows live in the same canonical collection.  They are
            # explicitly outside this source-only migration and must not block it.
            skipped.append({"code": "out_of_scope_record", "public_id": public_id})
            continue
        try:
            anchor = source_record_id(source_key, _source_properties(record))
        except SourceIdentityError as exc:
            diagnostics.append(
                {"code": "missing_authoritative_anchor", "public_id": public_id, "detail": str(exc)}
            )
            continue
        records_by_public_id.setdefault(public_id, record)
        by_anchor.setdefault((source_key, anchor), []).append(public_id)

    for (source_key, anchor), public_ids in sorted(by_anchor.items()):
        if len(public_ids) != 1:
            diagnostics.append(
                {
                    "code": "ambiguous_anchor",
                    "source_key": source_key,
                    "source_record_id": anchor,
                    "public_ids": ",".join(sorted(public_ids)),
                }
            )
            continue
        public_id = public_ids[0]
        if public_id in duplicate_public_ids:
            diagnostics.append({"code": "duplicate_public_id", "public_id": public_id})
            continue
        existing = registered.get((source_key, anchor))
        if existing is not None and existing != public_id:
            diagnostics.append(
                {
                    "code": "registry_conflict",
                    "source_key": source_key,
                    "source_record_id": anchor,
                    "public_ids": f"{existing},{public_id}",
                }
            )
            continue
        if existing is None:
            discovery = _validated_discovery_value(records_by_public_id[public_id])
            if discovery is None:
                diagnostics.append({"code": "invalid_discovery_date", "public_id": public_id})
                continue
            candidates.append(
                {
                    "source_key": source_key,
                    "source_record_id": anchor,
                    "public_id": public_id,
                    "first_discovered_at": discovery,
                }
            )

    report = {
        "report_version": "c03-source-identity-backfill-v1",
        "candidates": candidates,
        "diagnostics": sorted(diagnostics, key=_json_key),
        "skipped": sorted(skipped, key=_json_key),
        "candidate_count": len(candidates),
        "diagnostic_count": len(diagnostics),
    }
    report["digest"] = _digest(report)
    return report


def apply_source_identity_backfill(
    session: Session,
    *,
    expected_digest: str,
) -> dict[str, Any]:
    """Apply an operator-reviewed dry run, or fail without guessing if it changed."""
    unit = CollectionUnitOfWork(session)
    with unit.canonical_mutation():
        report = dry_run_source_identity_backfill(session)
        if report["digest"] != expected_digest:
            raise ValueError("Backfill report changed; create and review a new dry-run report")
        if report["diagnostics"]:
            raise ValueError("Backfill report has unresolved diagnostics; no mappings were applied")
        records = {
            str(record["public_id"]): record
            for record in unit.list_processed("development_records")
            if isinstance(record.get("public_id"), str)
        }
        for candidate in report["candidates"]:
            public_id = candidate["public_id"]
            record = records.get(public_id)
            if record is None:
                raise ValueError("Canonical row changed during backfill review; rerun dry run")
            session.add(
                SourceIdentityRegistry(
                    source_key=candidate["source_key"],
                    source_record_id=candidate["source_record_id"],
                    public_id=public_id,
                    first_discovered_at=_parse_discovery(candidate["first_discovered_at"]),
                    last_observed_at=None,
                )
            )
        session.flush()
        return {
            "applied": len(report["candidates"]),
            "digest": report["digest"],
            "mapping": export_source_identity_mapping(session),
        }


def export_source_identity_mapping(session: Session) -> list[dict[str, str]]:
    """Return a stable recovery artifact; callers choose an explicit output location."""
    rows = session.scalars(
        select(SourceIdentityRegistry).order_by(
            SourceIdentityRegistry.source_key,
            SourceIdentityRegistry.source_record_id,
            SourceIdentityRegistry.id,
        )
    ).all()
    return [
        {
            "source_key": row.source_key,
            "source_record_id": row.source_record_id,
            "public_id": row.public_id,
        }
        for row in rows
    ]


def _source_key(record: dict[str, Any]) -> str | None:
    key = record.get("source_key")
    if isinstance(key, str) and key in SOURCE_ID_FIELDS:
        return key
    if record.get("development_type") == "public_submission":
        return None
    source_url = record.get("source_url")
    return SOURCE_URLS.get(source_url) if isinstance(source_url, str) else None


def _source_properties(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("source_fields")
    return fields if isinstance(fields, dict) else {}


def _validated_discovery_value(record: dict[str, Any]) -> str | None:
    value = record.get("date_discovered")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            parsed = parsed.replace(tzinfo=parsed.tzinfo or UTC)
            return parsed.isoformat()
        except ValueError:
            pass
    return None


def _parse_discovery(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _digest(report: dict[str, Any]) -> str:
    payload = {key: value for key, value in report.items() if key != "digest"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_key(value: dict[str, str]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
