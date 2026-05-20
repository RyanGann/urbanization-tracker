from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import delete, select

from app.config import get_settings

HUNTSVILLE_CENTER: tuple[float, float] = (-86.5861, 34.7304)
PUBLIC_SUBMISSION_SOURCE = "public-submission://local"
DUPLICATE_TOKEN_FANOUT_LIMIT = 100
PHASE3_COLLECTIONS = (
    "source_documents",
    "agenda_staged_records",
    "submission_staged_records",
    "development_records",
    "public_submissions",
    "watch_areas",
    "alerts",
    "duplicate_candidates",
    "record_versions",
    "change_log",
    "agenda_health",
)

_memory_only = False
_memory_collections: dict[str, list[dict[str, Any]]] = {}


def reset_phase3_state(*, force_memory: bool = True) -> None:
    global _memory_only
    _memory_only = force_memory
    _memory_collections.clear()


def list_source_documents() -> list[dict[str, Any]]:
    return _read_collection("source_documents")


def list_phase3_staged_records() -> list[dict[str, Any]]:
    return [
        *_read_collection("agenda_staged_records"),
        *_read_collection("submission_staged_records"),
    ]


def list_phase3_development_records() -> list[dict[str, Any]]:
    return _read_collection("development_records")


def list_public_submissions() -> list[dict[str, Any]]:
    return _read_collection("public_submissions")


def list_watch_areas() -> list[dict[str, Any]]:
    alerts = list_alerts()
    alert_counts: dict[str, int] = {}
    for alert in alerts:
        watch_area_id = str(alert["watch_area_id"])
        alert_counts[watch_area_id] = alert_counts.get(watch_area_id, 0) + 1
    watch_areas = _read_collection("watch_areas")
    for watch_area in watch_areas:
        watch_area["alert_count"] = alert_counts.get(str(watch_area["id"]), 0)
    return watch_areas


def list_alerts() -> list[dict[str, Any]]:
    return _read_collection("alerts")


def list_duplicate_candidates() -> list[dict[str, Any]]:
    return _read_collection("duplicate_candidates")


def get_phase3_staged_record(staged_id: str) -> dict[str, Any] | None:
    for collection_name in ("agenda_staged_records", "submission_staged_records"):
        for record in _read_collection(collection_name):
            if record["id"] == staged_id:
                return record
    return None


def set_phase3_staged_review_status(
    staged_id: str,
    review_status: str,
    notes: str | None = None,
) -> dict[str, Any] | None:
    for collection_name in ("agenda_staged_records", "submission_staged_records"):
        records = _read_collection(collection_name)
        for record in records:
            if record["id"] == staged_id:
                record["review_status"] = review_status
                record["review_notes"] = notes
                _write_collection(collection_name, records)
                _sync_submission_status(record, review_status)
                return copy.deepcopy(record)
    return None


def publish_phase3_staged_record(
    staged_id: str,
    notes: str | None,
) -> dict[str, Any] | None:
    staged = get_phase3_staged_record(staged_id)
    if staged is None:
        return None

    staged["review_status"] = "approved"
    staged["review_notes"] = notes
    published = copy.deepcopy(staged.get("publish_record") or _publish_record_from_staged(staged))
    published["review_status"] = "published"
    published["date_last_checked"] = _today()

    records = _read_collection("development_records")
    if not any(record["public_id"] == published["public_id"] for record in records):
        records.append(published)
        _write_collection("development_records", records)
        _append_record_version(published, changed_by="reviewer", change_type="published")
        _append_change_log(
            published,
            change_type="published",
            summary=f"{published['title']} was published from a reviewer-gated source.",
        )
    set_phase3_staged_review_status(staged_id, "approved", notes=notes)
    return published


def create_public_submission(
    payload: dict[str, Any],
    published_records: list[Any],
) -> dict[str, Any]:
    created_at = _now()
    submission_id = _stable_id("submission", payload["title"], created_at)
    staged_id = f"stage-{submission_id}"
    geometry = payload.get("geometry") or {
        "type": "Point",
        "coordinates": [HUNTSVILLE_CENTER[0], HUNTSVILLE_CENTER[1]],
    }
    public_id = _stable_id("hsv-public-submission", payload["title"], created_at)
    source_url = payload.get("source_url") or PUBLIC_SUBMISSION_SOURCE

    submission = {
        "id": submission_id,
        "title": payload["title"],
        "source_url": payload.get("source_url"),
        "notes": payload["notes"],
        "submitter_contact_hash": _hash_contact(payload.get("submitter_contact")),
        "status": "pending",
        "created_at": created_at,
        "staged_record_id": staged_id,
    }
    staged = {
        "id": staged_id,
        "title": payload["title"],
        "description": "Public submission awaiting reviewer validation.",
        "development_type": "public_submission",
        "source_status": "submitted",
        "normalized_status": "proposed",
        "source_url": source_url,
        "source_agency": "Public submission",
        "date_discovered": created_at[:10],
        "review_status": "pending",
        "record_confidence": "low",
        "geometry_source": "Public-submitted geometry or default Huntsville review point",
        "geometry_confidence": "low",
        "geometry": geometry,
        "source_payload": {
            "submission_id": submission_id,
            "notes": payload["notes"],
            "source_url": payload.get("source_url"),
        },
        "normalization_notes": (
            "Manual public submission. A reviewer must verify the source link, status, "
            "geometry, and duplicate risk before publishing."
        ),
        "publish_record": {
            "public_id": public_id,
            "title": payload["title"],
            "description": payload["notes"],
            "development_type": "public_submission",
            "status": "proposed",
            "source_status": "submitted",
            "source_url": source_url,
            "source_agency": "Public submission",
            "date_discovered": created_at[:10],
            "date_last_checked": created_at[:10],
            "application_date": None,
            "approval_date": None,
            "permit_issue_date": None,
            "review_status": "published",
            "confidence_level": "low",
            "geometry_source": "Reviewer-approved public submission geometry",
            "geometry_confidence": "low",
            "geometry": geometry,
            "centroid": _geometry_centroid(geometry),
            "area_sq_m": None,
            "address": None,
            "parcel_ids": [],
            "source_fields": {
                "submission_id": submission_id,
                "source_url": payload.get("source_url"),
                "review_required": True,
            },
            "proximity_flags": [],
        },
    }

    submissions = _read_collection("public_submissions")
    submissions.append(submission)
    _write_collection("public_submissions", submissions)

    staged_records = _read_collection("submission_staged_records")
    staged_records.append(staged)
    _write_collection("submission_staged_records", staged_records)
    _append_duplicate_candidates([staged], published_records)
    return submission


def set_public_submission_status(
    submission_id: str,
    status: str,
    notes: str | None = None,
) -> dict[str, Any] | None:
    submissions = _read_collection("public_submissions")
    for submission in submissions:
        if submission["id"] == submission_id:
            submission["status"] = status
            submission["review_notes"] = notes
            _write_collection("public_submissions", submissions)
            staged_id = str(submission["staged_record_id"])
            staged_status = "needs_info" if status == "needs_info" else status
            set_phase3_staged_review_status(staged_id, staged_status, notes=notes)
            return copy.deepcopy(submission)
    return None


def create_watch_area(payload: dict[str, Any], published_records: list[Any]) -> dict[str, Any]:
    watch_area_id = _stable_id("watch", payload["name"], payload["email"], _now())
    watch_area = {
        "id": watch_area_id,
        "name": payload["name"],
        "email_hash": _hash_contact(payload["email"]) or "",
        "email_hint": _email_hint(payload["email"]),
        "geometry": payload["geometry"],
        "filters": payload.get("filters") or {},
        "created_at": _now(),
        "alert_count": 0,
    }
    watch_areas = _read_collection("watch_areas")
    watch_areas.append(watch_area)
    _write_collection("watch_areas", watch_areas)

    alerts = _read_collection("alerts")
    new_alerts = _alerts_for_watch_area(watch_area, published_records)
    alerts.extend(new_alerts)
    _write_collection("alerts", _dedupe(alerts, key="id"))
    watch_area["alert_count"] = len(new_alerts)
    return watch_area


def record_versions_for(public_id: str, fallback_record: Any | None = None) -> list[dict[str, Any]]:
    explicit = [
        version
        for version in _read_collection("record_versions")
        if version["public_id"] == public_id
    ]
    if explicit:
        return sorted(explicit, key=lambda version: version["version_number"])
    if fallback_record is None:
        return []
    snapshot = _record_to_dict(fallback_record)
    return [
        {
            "id": f"version-{public_id}-current",
            "public_id": public_id,
            "version_number": 1,
            "changed_at": snapshot.get("date_last_checked") or snapshot.get("date_discovered"),
            "changed_by": "source-ingestion",
            "change_type": "current_snapshot",
            "snapshot": snapshot,
        }
    ]


def change_log_for(records: list[Any], *, limit: int = 50) -> list[dict[str, Any]]:
    explicit = _read_collection("change_log")
    synthetic: list[dict[str, Any]] = []
    for record in records[:limit]:
        snapshot = _record_to_dict(record)
        public_id = str(snapshot["public_id"])
        synthetic.append(
            {
                "id": f"change-{public_id}-current",
                "public_id": public_id,
                "title": str(snapshot["title"]),
                "changed_at": str(snapshot.get("date_last_checked") or snapshot["date_discovered"]),
                "change_type": "current_snapshot",
                "summary": "Current published source snapshot is available for review.",
            }
        )
    combined = [*explicit, *synthetic]
    combined.sort(key=lambda entry: str(entry["changed_at"]), reverse=True)
    return combined[:limit]


def replace_agenda_artifacts(
    *,
    source_documents: list[dict[str, Any]],
    staged_records: list[dict[str, Any]],
    duplicate_candidates: list[dict[str, Any]],
    health: dict[str, Any],
) -> None:
    _write_collection("source_documents", source_documents)
    _write_collection("agenda_staged_records", staged_records)
    _write_collection("duplicate_candidates", duplicate_candidates)
    _write_collection("agenda_health", [health])


def agenda_health() -> dict[str, Any] | None:
    health_records = _read_collection("agenda_health")
    if not health_records:
        return None
    return health_records[0]


def migrate_artifact_collections_to_postgres(
    collection_names: tuple[str, ...] = PHASE3_COLLECTIONS,
) -> dict[str, int]:
    migrated: dict[str, int] = {}
    for name in collection_names:
        path = _collection_path(name)
        if not path.exists():
            migrated[name] = 0
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            migrated[name] = 0
            continue
        items = [item for item in payload if isinstance(item, dict)]
        _write_postgres_collection(name, items)
        migrated[name] = len(items)
    return migrated


def build_duplicate_candidates(
    staged_records: list[dict[str, Any]],
    published_records: list[Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    indexed_published: list[tuple[dict[str, Any], set[str]]] = []
    token_counts: dict[str, int] = {}
    for published_record in published_records:
        published = _record_to_dict(published_record)
        published_tokens = _title_tokens(str(published["title"]))
        if published_tokens:
            indexed_published.append((published, published_tokens))
            for token in published_tokens:
                token_counts[token] = token_counts.get(token, 0) + 1

    published_by_token: dict[str, list[tuple[dict[str, Any], set[str]]]] = {}
    for published, published_tokens in indexed_published:
        for token in published_tokens:
            if token_counts[token] > DUPLICATE_TOKEN_FANOUT_LIMIT:
                continue
            published_by_token.setdefault(token, []).append((published, published_tokens))

    for staged in staged_records:
        staged_tokens = _title_tokens(str(staged["title"]))
        if not staged_tokens:
            continue
        candidate_pool: dict[str, tuple[dict[str, Any], set[str]]] = {}
        for token in staged_tokens:
            for published, published_tokens in published_by_token.get(token, []):
                candidate_pool[str(published["public_id"])] = (published, published_tokens)
        for published, published_tokens in candidate_pool.values():
            overlap = staged_tokens & published_tokens
            score = len(overlap) / max(len(staged_tokens | published_tokens), 1)
            if score >= 0.45:
                reasons = [f"Title token overlap: {', '.join(sorted(overlap))}"]
                if staged.get("normalized_status") == published.get("status"):
                    score += 0.1
                    reasons.append("Normalized status matches")
                candidates.append(
                    {
                        "id": _stable_id(
                            "duplicate",
                            staged["id"],
                            published["public_id"],
                        ),
                        "staged_record_id": staged["id"],
                        "staged_title": staged["title"],
                        "candidate_public_id": published["public_id"],
                        "candidate_title": published["title"],
                        "score": round(min(score, 1.0), 2),
                        "reasons": reasons,
                    }
                )
    candidates.sort(key=lambda candidate: candidate["score"], reverse=True)
    return candidates


def _append_duplicate_candidates(staged_records: list[dict[str, Any]], records: list[Any]) -> None:
    existing = _read_collection("duplicate_candidates")
    existing.extend(build_duplicate_candidates(staged_records, records))
    _write_collection("duplicate_candidates", _dedupe(existing, key="id"))


def _sync_submission_status(staged: dict[str, Any], review_status: str) -> None:
    submission_id = staged.get("source_payload", {}).get("submission_id")
    if not submission_id:
        return
    submissions = _read_collection("public_submissions")
    for submission in submissions:
        if submission["id"] == submission_id:
            submission["status"] = review_status
    _write_collection("public_submissions", submissions)


def _publish_record_from_staged(staged: dict[str, Any]) -> dict[str, Any]:
    geometry = staged["geometry"]
    return {
        "public_id": _stable_id("hsv-reviewed", staged["title"], staged["id"]),
        "title": staged["title"],
        "description": staged["description"],
        "development_type": staged["development_type"],
        "status": staged["normalized_status"],
        "source_status": staged["source_status"],
        "source_url": staged["source_url"],
        "source_agency": staged["source_agency"],
        "date_discovered": staged["date_discovered"],
        "date_last_checked": _today(),
        "application_date": None,
        "approval_date": None,
        "permit_issue_date": None,
        "review_status": "published",
        "confidence_level": staged["record_confidence"],
        "geometry_source": staged["geometry_source"],
        "geometry_confidence": staged["geometry_confidence"],
        "geometry": geometry,
        "centroid": _geometry_centroid(geometry),
        "area_sq_m": None,
        "address": None,
        "parcel_ids": [],
        "source_fields": staged.get("source_payload", {}),
        "proximity_flags": [],
    }


def _append_record_version(
    record: dict[str, Any],
    *,
    changed_by: str,
    change_type: str,
) -> None:
    versions = _read_collection("record_versions")
    public_id = str(record["public_id"])
    version_number = (
        max(
            (
                int(version["version_number"])
                for version in versions
                if version["public_id"] == public_id
            ),
            default=0,
        )
        + 1
    )
    versions.append(
        {
            "id": f"version-{public_id}-{version_number}",
            "public_id": public_id,
            "version_number": version_number,
            "changed_at": _now(),
            "changed_by": changed_by,
            "change_type": change_type,
            "snapshot": copy.deepcopy(record),
        }
    )
    _write_collection("record_versions", versions)


def _append_change_log(record: dict[str, Any], *, change_type: str, summary: str) -> None:
    entries = _read_collection("change_log")
    entries.append(
        {
            "id": _stable_id("change", record["public_id"], change_type, _now()),
            "public_id": record["public_id"],
            "title": record["title"],
            "changed_at": _now(),
            "change_type": change_type,
            "summary": summary,
        }
    )
    _write_collection("change_log", entries)


def _alerts_for_watch_area(
    watch_area: dict[str, Any],
    published_records: list[Any],
) -> list[dict[str, Any]]:
    watch_bbox = _geometry_bbox(watch_area["geometry"])
    if watch_bbox is None:
        return []
    filters = watch_area.get("filters") or {}
    statuses = set(filters.get("statuses") or [])
    development_types = set(filters.get("development_types") or [])
    alerts: list[dict[str, Any]] = []
    for record_value in published_records:
        record = _record_to_dict(record_value)
        if statuses and record.get("status") not in statuses:
            continue
        if development_types and record.get("development_type") not in development_types:
            continue
        record_bbox = _geometry_bbox(record.get("geometry") or {})
        if record_bbox is None or not _bbox_intersects(watch_bbox, record_bbox):
            continue
        alerts.append(
            {
                "id": _stable_id("alert", watch_area["id"], record["public_id"], "new_match"),
                "watch_area_id": watch_area["id"],
                "record_public_id": record["public_id"],
                "record_title": record["title"],
                "alert_type": "new_match",
                "status": "queued",
                "delivery_channel": "email",
                "created_at": _now(),
                "sent_at": None,
                "summary": f"{record['title']} intersects the watch area {watch_area['name']}.",
            }
        )
    return alerts


def _read_collection(name: str) -> list[dict[str, Any]]:
    if _memory_only:
        return copy.deepcopy(_memory_collections.get(name, []))
    if _use_postgres_store():
        return _read_postgres_collection(name)
    path = _collection_path(name)
    if not path.exists():
        return copy.deepcopy(_memory_collections.get(name, []))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return copy.deepcopy(payload)


def _write_collection(name: str, items: list[dict[str, Any]]) -> None:
    if _memory_only:
        _memory_collections[name] = copy.deepcopy(items)
        return
    if _use_postgres_store():
        _write_postgres_collection(name, items)
        return
    path = _collection_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _collection_path(name: str) -> Path:
    return get_settings().ingestion_data_dir / "processed" / f"phase3_{name}.json"


def _use_postgres_store() -> bool:
    return get_settings().phase3_store_backend.lower() == "postgres"


def _read_postgres_collection(name: str) -> list[dict[str, Any]]:
    from app.db import SessionLocal
    from app.models import Phase3CollectionItem

    with SessionLocal() as db:
        rows = db.scalars(
            select(Phase3CollectionItem)
            .where(Phase3CollectionItem.collection_name == name)
            .order_by(Phase3CollectionItem.sort_order, Phase3CollectionItem.id)
        ).all()
        return [copy.deepcopy(row.payload_json) for row in rows]


def _write_postgres_collection(name: str, items: list[dict[str, Any]]) -> None:
    from app.db import SessionLocal
    from app.models import Phase3CollectionItem

    with SessionLocal.begin() as db:
        db.execute(
            delete(Phase3CollectionItem).where(Phase3CollectionItem.collection_name == name)
        )
        db.add_all(
            Phase3CollectionItem(
                collection_name=name,
                item_id=_collection_item_id(name, index, item),
                sort_order=index,
                payload_json=copy.deepcopy(item),
            )
            for index, item in enumerate(items)
        )


def _collection_item_id(name: str, index: int, item: dict[str, Any]) -> str:
    for key in ("id", "public_id", "run_id"):
        value = item.get(key)
        if value:
            return str(value)[:255]
    return f"{name}-{index}"


def _record_to_dict(record: Any) -> dict[str, Any]:
    if hasattr(record, "model_dump"):
        return cast(dict[str, Any], record.model_dump())
    if isinstance(record, dict):
        return copy.deepcopy(record)
    raise TypeError(f"Unsupported record type: {type(record)!r}")


def _geometry_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float] | None:
    coordinates = geometry.get("coordinates")
    values: list[tuple[float, float]] = []
    _collect_coordinates(coordinates, values)
    if not values:
        return None
    xs = [value[0] for value in values]
    ys = [value[1] for value in values]
    return min(xs), min(ys), max(xs), max(ys)


def _collect_coordinates(value: Any, output: list[tuple[float, float]]) -> None:
    if (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], int | float)
        and isinstance(value[1], int | float)
    ):
        output.append((float(value[0]), float(value[1])))
        return
    if isinstance(value, list):
        for item in value:
            _collect_coordinates(item, output)


def _geometry_centroid(geometry: dict[str, Any]) -> tuple[float, float]:
    bbox = _geometry_bbox(geometry)
    if bbox is None:
        return HUNTSVILLE_CENTER
    west, south, east, north = bbox
    return ((west + east) / 2, (south + north) / 2)


def _bbox_intersects(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    left_west, left_south, left_east, left_north = left
    right_west, right_south, right_east, right_north = right
    return not (
        left_east < right_west
        or right_east < left_west
        or left_north < right_south
        or right_north < left_south
    )


def _dedupe(records: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for record in records:
        deduped[str(record[key])] = record
    return list(deduped.values())


def _title_tokens(title: str) -> set[str]:
    stop_words = {"at", "the", "of", "and", "phase", "ph", "subdivision", "addition"}
    return {
        token
        for token in re.sub(r"[^a-z0-9]+", " ", title.lower()).split()
        if len(token) > 2 and token not in stop_words
    }


def _hash_contact(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _email_hint(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    return f"{local[:2]}***@{domain}"


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    slug_bits = [_slug(str(part)) for part in parts[:1] if str(part).strip()]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    slug = "-".join(slug_bits)
    return f"{prefix}-{slug}-{digest}" if slug else f"{prefix}-{digest}"


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-+", "-", text)[:64] or "item"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _today() -> str:
    return datetime.now(UTC).date().isoformat()
