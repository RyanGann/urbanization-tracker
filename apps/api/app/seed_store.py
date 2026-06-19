from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.processed_store import read_processed_list, read_processed_payload
from app.schemas import DevelopmentRecord, EnvironmentalOverlay, StagedDevelopmentRecord

SEED_PATH = Path(__file__).parent / "seed" / "seed_data.json"

_seed_data: dict[str, Any] | None = None
_development_records: list[dict[str, Any]] = []
_staged_records: list[dict[str, Any]] = []
_force_seed_records = False


def _load_seed_data() -> dict[str, Any]:
    global _seed_data
    if _seed_data is None:
        _seed_data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return _seed_data


def reset_seed_state(*, force_seed: bool = True) -> None:
    global _force_seed_records
    seed = _load_seed_data()
    _development_records.clear()
    _development_records.extend(copy.deepcopy(seed["development_records"]))
    _staged_records.clear()
    _staged_records.extend(copy.deepcopy(seed["staged_records"]))
    _force_seed_records = force_seed
    from app.phase3_store import reset_phase3_state

    reset_phase3_state(force_memory=force_seed)


def _ensure_loaded() -> None:
    if not _development_records and not _staged_records:
        reset_seed_state(force_seed=False)


def _load_processed_records() -> list[dict[str, Any]] | None:
    return read_processed_list("development_records")


def _load_processed_staged_records() -> list[dict[str, Any]] | None:
    return read_processed_list("staged_development_records")


def _load_processed_overlays() -> list[dict[str, Any]] | None:
    return read_processed_list("environmental_overlays")


def load_source_health() -> dict[str, Any]:
    payload = read_processed_payload(
        "source_health",
        default={"status": "unknown", "sources": [], "records": {}},
    )
    if payload is None:
        payload = {"status": "unknown", "sources": [], "records": {}}

    from app.phase3_store import agenda_health

    phase3_health = agenda_health()
    if phase3_health:
        payload = copy.deepcopy(payload)
        sources = payload.setdefault("sources", [])
        if isinstance(sources, list):
            sources.append(copy.deepcopy(phase3_health))
        records = payload.setdefault("records", {})
        if isinstance(records, dict):
            records["agenda_documents"] = phase3_health.get("documents_seen", 0)
            records["agenda_staged"] = phase3_health.get("records_created", 0)
        if phase3_health.get("status") == "failing":
            payload["status"] = "degraded"
        elif payload.get("status") == "unknown":
            payload["status"] = "healthy"
    return payload


def list_development_records(
    *,
    statuses: list[str] | None = None,
    development_types: list[str] | None = None,
    confidence_levels: list[str] | None = None,
    flag_types: list[str] | None = None,
) -> list[DevelopmentRecord]:
    _ensure_loaded()
    processed_records = None if _force_seed_records else _load_processed_records()
    records = copy.deepcopy(processed_records or _development_records)
    from app.phase3_store import list_phase3_development_records

    records.extend(list_phase3_development_records())

    if statuses:
        status_set = set(statuses)
        records = [record for record in records if record["status"] in status_set]

    if development_types:
        type_set = set(development_types)
        records = [record for record in records if record["development_type"] in type_set]

    if confidence_levels:
        confidence_set = set(confidence_levels)
        records = [record for record in records if record["confidence_level"] in confidence_set]

    if flag_types:
        flag_set = set(flag_types)
        records = [
            record
            for record in records
            if any(flag["flag_type"] in flag_set for flag in record.get("proximity_flags", []))
        ]

    return [DevelopmentRecord.model_validate(record) for record in records]


def get_development_record(public_id: str) -> DevelopmentRecord | None:
    _ensure_loaded()
    processed_records = None if _force_seed_records else _load_processed_records()
    records = copy.deepcopy(processed_records or _development_records)
    from app.phase3_store import list_phase3_development_records

    records.extend(list_phase3_development_records())
    for record in records:
        if record["public_id"] == public_id:
            return DevelopmentRecord.model_validate(copy.deepcopy(record))
    return None


def development_records_geojson(records: list[DevelopmentRecord]) -> dict[str, Any]:
    features = []
    for record in records:
        payload = record.model_dump()
        geometry = payload.pop("geometry")
        features.append(
            {
                "type": "Feature",
                "id": record.public_id,
                "geometry": geometry,
                "properties": payload,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def list_environmental_overlays() -> list[EnvironmentalOverlay]:
    processed_overlays = None if _force_seed_records else _load_processed_overlays()
    if processed_overlays is not None:
        return [
            EnvironmentalOverlay.model_validate(copy.deepcopy(overlay))
            for overlay in processed_overlays
        ]

    seed = _load_seed_data()
    return [
        EnvironmentalOverlay.model_validate(copy.deepcopy(overlay))
        for overlay in seed["environmental_overlays"]
    ]


def list_staged_records() -> list[StagedDevelopmentRecord]:
    _ensure_loaded()
    processed_staged = None if _force_seed_records else _load_processed_staged_records()
    if processed_staged is not None:
        records = copy.deepcopy(processed_staged)
    else:
        records = copy.deepcopy(_staged_records)
    from app.phase3_store import list_phase3_staged_records

    records.extend(list_phase3_staged_records())
    return [StagedDevelopmentRecord.model_validate(copy.deepcopy(record)) for record in records]


def get_staged_record(staged_id: str) -> dict[str, Any] | None:
    _ensure_loaded()
    for staged in _staged_records:
        if staged["id"] == staged_id:
            return staged
    return None


def approve_staged_record(staged_id: str, notes: str | None = None) -> DevelopmentRecord | None:
    staged = get_staged_record(staged_id)
    if staged is None:
        from app.phase3_store import publish_phase3_staged_record

        published = publish_phase3_staged_record(staged_id, notes=notes)
        if published is None:
            return None
        return DevelopmentRecord.model_validate(published)

    staged["review_status"] = "approved"
    staged["review_notes"] = notes
    published = copy.deepcopy(staged["publish_record"])
    if not any(record["public_id"] == published["public_id"] for record in _development_records):
        _development_records.append(published)
    return DevelopmentRecord.model_validate(published)


def set_staged_review_status(
    staged_id: str,
    review_status: str,
    notes: str | None = None,
) -> StagedDevelopmentRecord | None:
    staged = get_staged_record(staged_id)
    if staged is None:
        from app.phase3_store import set_phase3_staged_review_status

        phase3_staged = set_phase3_staged_review_status(
            staged_id,
            review_status,
            notes=notes,
        )
        if phase3_staged is None:
            return None
        return StagedDevelopmentRecord.model_validate(copy.deepcopy(phase3_staged))
    staged["review_status"] = review_status
    staged["review_notes"] = notes
    return StagedDevelopmentRecord.model_validate(copy.deepcopy(staged))


def export_reviewer_decisions() -> list[dict[str, Any]]:
    exported_at = datetime.now(UTC).isoformat()
    return [
        {
            "staged_id": record.id,
            "title": record.title,
            "source_url": record.source_url,
            "review_status": record.review_status,
            "review_notes": getattr(record, "review_notes", None),
            "exported_at": exported_at,
        }
        for record in list_staged_records()
    ]


def import_reviewer_decisions(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    applied = 0
    missing: list[str] = []
    for decision in decisions:
        staged_id = str(decision["staged_id"])
        review_status = str(decision["review_status"])
        notes = decision.get("notes")
        result: DevelopmentRecord | StagedDevelopmentRecord | None
        if review_status in {"approved", "published"}:
            result = approve_staged_record(staged_id, notes=notes)
        else:
            result = set_staged_review_status(staged_id, review_status, notes=notes)
        if result is None:
            missing.append(staged_id)
        else:
            applied += 1
    return {"applied": applied, "missing": missing}
