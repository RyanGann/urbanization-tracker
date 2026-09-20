from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config import get_settings
from app.data_availability import Availability, DataUnavailableError
from app.processed_store import read_processed_list_result, read_processed_payload_result
from app.schemas import DevelopmentRecord, EnvironmentalOverlay, StagedDevelopmentRecord

SEED_PATH = Path(__file__).parent / "seed" / "seed_data.json"

_seed_data: dict[str, Any] | None = None
_development_records: list[dict[str, Any]] = []
_staged_records: list[dict[str, Any]] = []
_force_seed_records = False
_active_data_mode: str | None = None


def _load_seed_data() -> dict[str, Any]:
    global _seed_data
    if _seed_data is None:
        _seed_data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return _seed_data


def _initialize_demo_records(*, force_seed: bool) -> None:
    global _active_data_mode, _force_seed_records
    seed = _load_seed_data()
    _development_records.clear()
    _development_records.extend(copy.deepcopy(seed["development_records"]))
    _staged_records.clear()
    _staged_records.extend(copy.deepcopy(seed["staged_records"]))
    _force_seed_records = force_seed
    _active_data_mode = "demo"


def reset_seed_state(*, force_seed: bool = True) -> None:
    """Reset the isolated demo session without selecting demo mode."""
    _initialize_demo_records(force_seed=force_seed)
    from app.phase3_store import reset_phase3_state

    reset_phase3_state(force_memory=get_settings().data_mode == "demo")


def _ensure_loaded() -> None:
    if get_settings().data_mode == "demo" and _active_data_mode != "demo":
        _initialize_demo_records(force_seed=True)


def _load_processed_records() -> list[dict[str, Any]] | None:
    result = read_processed_list_result("development_records")
    if result.availability is Availability.UNINITIALIZED:
        return None
    return result.require_ready(collection="development_records")


def _load_processed_staged_records() -> list[dict[str, Any]] | None:
    result = read_processed_list_result("staged_development_records")
    if result.availability is Availability.UNINITIALIZED:
        return None
    return result.require_ready(collection="staged_development_records")


def _load_processed_overlays() -> list[dict[str, Any]] | None:
    result = read_processed_list_result("environmental_overlays")
    if result.availability is Availability.UNINITIALIZED:
        return None
    return result.require_ready(collection="environmental_overlays")


def _validated_development_records(records: list[dict[str, Any]]) -> list[DevelopmentRecord]:
    try:
        return [DevelopmentRecord.model_validate(record) for record in records]
    except ValidationError as exc:
        raise DataUnavailableError(
            collection="development_records", availability=Availability.UNAVAILABLE
        ) from exc


def development_records_availability() -> Availability:
    if get_settings().data_mode == "demo":
        return Availability.READY
    result = read_processed_list_result("development_records")
    if result.availability is not Availability.READY:
        return result.availability
    try:
        _validated_development_records(result.items or [])
    except DataUnavailableError:
        return Availability.UNAVAILABLE
    from app.phase3_store import list_phase3_development_records

    try:
        _validated_development_records(list_phase3_development_records())
    except DataUnavailableError:
        return Availability.UNAVAILABLE
    return Availability.READY


def load_source_health() -> dict[str, Any]:
    if get_settings().data_mode == "demo":
        payload = {"status": "unknown", "sources": [], "records": {}}
    else:
        result = read_processed_payload_result("source_health")
        payload = result.require_ready(collection="source_health")

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
    if get_settings().data_mode == "demo":
        _ensure_loaded()
        records = copy.deepcopy(_development_records)
    else:
        processed_records = _load_processed_records()
        if processed_records is None:
            from app.data_availability import DataUnavailableError

            raise DataUnavailableError(
                collection="development_records", availability=Availability.UNINITIALIZED
            )
        records = copy.deepcopy(processed_records)
    from app.phase3_store import list_phase3_development_records

    records.extend(list_phase3_development_records())
    records = [record.model_dump() for record in _validated_development_records(records)]

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

    try:
        return [DevelopmentRecord.model_validate(record) for record in records]
    except ValidationError as exc:
        raise DataUnavailableError(
            collection="development_records", availability=Availability.UNAVAILABLE
        ) from exc


def get_development_record(public_id: str) -> DevelopmentRecord | None:
    if get_settings().data_mode == "demo":
        _ensure_loaded()
        records = copy.deepcopy(_development_records)
    else:
        processed_records = _load_processed_records()
        if processed_records is None:
            from app.data_availability import DataUnavailableError

            raise DataUnavailableError(
                collection="development_records", availability=Availability.UNINITIALIZED
            )
        records = copy.deepcopy(processed_records)
    from app.phase3_store import list_phase3_development_records

    records.extend(list_phase3_development_records())
    records = [record.model_dump() for record in _validated_development_records(records)]
    for record in records:
        if record["public_id"] == public_id:
            try:
                return DevelopmentRecord.model_validate(copy.deepcopy(record))
            except ValidationError as exc:
                raise DataUnavailableError(
                    collection="development_records", availability=Availability.UNAVAILABLE
                ) from exc
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
    if get_settings().data_mode == "demo":
        seed = _load_seed_data()
        overlays = seed["environmental_overlays"]
    else:
        processed_overlays = _load_processed_overlays()
        if processed_overlays is None:
            from app.data_availability import DataUnavailableError

            raise DataUnavailableError(
                collection="environmental_overlays", availability=Availability.UNINITIALIZED
            )
        overlays = processed_overlays
    try:
        return [EnvironmentalOverlay.model_validate(copy.deepcopy(overlay)) for overlay in overlays]
    except ValidationError as exc:
        raise DataUnavailableError(
            collection="environmental_overlays", availability=Availability.UNAVAILABLE
        ) from exc


def list_staged_records() -> list[StagedDevelopmentRecord]:
    if get_settings().data_mode == "demo":
        _ensure_loaded()
        records = copy.deepcopy(_staged_records)
    else:
        processed_staged = _load_processed_staged_records()
        if processed_staged is None:
            raise DataUnavailableError(
                collection="staged_development_records",
                availability=Availability.UNINITIALIZED,
            )
        records = copy.deepcopy(processed_staged)
    from app.phase3_store import list_phase3_staged_records

    records.extend(list_phase3_staged_records())
    try:
        return [StagedDevelopmentRecord.model_validate(copy.deepcopy(record)) for record in records]
    except ValidationError as exc:
        raise DataUnavailableError(
            collection="staged_development_records", availability=Availability.UNAVAILABLE
        ) from exc


def get_staged_record(staged_id: str) -> dict[str, Any] | None:
    if get_settings().data_mode == "demo":
        _ensure_loaded()
        records = _staged_records
    else:
        records = _load_processed_staged_records() or []
    for staged in records:
        if staged["id"] == staged_id:
            return staged
    return None


def approve_staged_record(staged_id: str, notes: str | None = None) -> DevelopmentRecord | None:
    if get_settings().data_mode == "live":
        # Processed ingestion rows are read-only until the durable C05 review path.
        # Only independently persisted phase3 staged rows may use the legacy action.
        from app.phase3_store import publish_phase3_staged_record

        published = publish_phase3_staged_record(staged_id, notes=notes)
        if published is None:
            return None
        return DevelopmentRecord.model_validate(published)
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
    if get_settings().data_mode == "live":
        from app.phase3_store import set_phase3_staged_review_status

        phase3_staged = set_phase3_staged_review_status(
            staged_id,
            review_status,
            notes=notes,
        )
        if phase3_staged is None:
            return None
        return StagedDevelopmentRecord.model_validate(copy.deepcopy(phase3_staged))
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
