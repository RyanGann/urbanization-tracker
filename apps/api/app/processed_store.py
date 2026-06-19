from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from app.config import get_settings

LIST_COLLECTIONS = (
    "development_records",
    "staged_development_records",
    "environmental_overlays",
)
SINGLETON_COLLECTIONS = ("source_health",)
PROCESSED_COLLECTIONS = (*LIST_COLLECTIONS, *SINGLETON_COLLECTIONS)
RAW_ARTIFACT_COLLECTIONS = ("raw_records",)


def read_processed_list(
    name: str,
    *,
    data_dir: Path | None = None,
) -> list[dict[str, Any]] | None:
    _require_collection(name, LIST_COLLECTIONS)
    if _use_postgres_store():
        return _read_postgres_items(name)
    path = _collection_path(data_dir or get_settings().ingestion_data_dir, name)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return None
    return [copy.deepcopy(item) for item in payload if isinstance(item, dict)]


def write_processed_list(
    name: str,
    items: list[dict[str, Any]],
    *,
    data_dir: Path | None = None,
) -> None:
    _require_collection(name, LIST_COLLECTIONS)
    if _use_postgres_store():
        _write_postgres_items(name, items)
        return
    _write_json(_collection_path(data_dir or get_settings().ingestion_data_dir, name), items)


def read_processed_payload(
    name: str,
    *,
    data_dir: Path | None = None,
    default: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    _require_collection(name, SINGLETON_COLLECTIONS)
    if _use_postgres_store():
        items = _read_postgres_items(name)
        if not items:
            return copy.deepcopy(default)
        return copy.deepcopy(items[0])
    path = _collection_path(data_dir or get_settings().ingestion_data_dir, name)
    if not path.exists():
        return copy.deepcopy(default)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return copy.deepcopy(default)
    return copy.deepcopy(payload)


def write_processed_payload(
    name: str,
    payload: dict[str, Any],
    *,
    data_dir: Path | None = None,
) -> None:
    _require_collection(name, SINGLETON_COLLECTIONS)
    if _use_postgres_store():
        _write_postgres_items(name, [payload])
        return
    _write_json(_collection_path(data_dir or get_settings().ingestion_data_dir, name), payload)


def migrate_processed_artifacts_to_postgres(
    *,
    data_dir: Path | None = None,
    collection_names: tuple[str, ...] = PROCESSED_COLLECTIONS,
) -> dict[str, int]:
    root = data_dir or get_settings().ingestion_data_dir
    migrated: dict[str, int] = {}
    for name in collection_names:
        if name in LIST_COLLECTIONS:
            items = _read_artifact_list(root, name)
            if items is None:
                continue
            _write_postgres_items(name, items)
            migrated[name] = len(items)
        elif name in SINGLETON_COLLECTIONS:
            payload = _read_artifact_payload(root, name)
            if payload is None:
                continue
            items = [payload]
            _write_postgres_items(name, items)
            migrated[name] = len(items)
        else:
            raise ValueError(f"Unknown processed collection: {name}")
    return migrated


def processed_store_status(*, data_dir: Path | None = None) -> dict[str, Any]:
    settings = get_settings()
    root = data_dir or settings.ingestion_data_dir
    database_counts: dict[str, int] = {}
    database_error: str | None = None
    if settings.processed_store_backend == "postgres":
        database_counts, database_error = _postgres_collection_counts()

    collections = []
    for name in PROCESSED_COLLECTIONS:
        artifact_count = _artifact_count(root, name)
        database_count = database_counts.get(name, 0)
        collections.append(
            {
                "name": name,
                "database_count": database_count,
                "artifact_count": artifact_count,
                "artifact_path": str(_collection_path(root, name)),
                "requires_migration": (
                    settings.processed_store_backend == "postgres"
                    and artifact_count > 0
                    and database_count == 0
                ),
            }
        )

    raw_artifacts = [
        {
            "name": name,
            "artifact_count": _artifact_count(root, name),
            "artifact_path": str(_collection_path(root, name)),
        }
        for name in RAW_ARTIFACT_COLLECTIONS
    ]

    return {
        "backend": settings.processed_store_backend,
        "database_first": settings.processed_store_backend == "postgres",
        "database_error": database_error,
        "collections": collections,
        "raw_artifacts": raw_artifacts,
    }


def _use_postgres_store() -> bool:
    return get_settings().processed_store_backend == "postgres"


def _collection_path(data_dir: Path, name: str) -> Path:
    return data_dir / "processed" / f"{name}.json"


def _read_artifact_list(data_dir: Path, name: str) -> list[dict[str, Any]] | None:
    path = _collection_path(data_dir, name)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    return [copy.deepcopy(item) for item in payload if isinstance(item, dict)]


def _read_artifact_payload(data_dir: Path, name: str) -> dict[str, Any] | None:
    path = _collection_path(data_dir, name)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return copy.deepcopy(payload)


def _artifact_count(data_dir: Path, name: str) -> int:
    if name in LIST_COLLECTIONS or name in RAW_ARTIFACT_COLLECTIONS:
        return len(_read_artifact_list(data_dir, name) or [])
    return 1 if _read_artifact_payload(data_dir, name) is not None else 0


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_postgres_items(name: str) -> list[dict[str, Any]]:
    from app.db import SessionLocal
    from app.models import ProcessedCollectionItem

    with SessionLocal() as db:
        rows = db.scalars(
            select(ProcessedCollectionItem)
            .where(ProcessedCollectionItem.collection_name == name)
            .order_by(ProcessedCollectionItem.sort_order, ProcessedCollectionItem.id)
        ).all()
        return [copy.deepcopy(row.payload_json) for row in rows]


def _write_postgres_items(name: str, items: list[dict[str, Any]]) -> None:
    from app.db import SessionLocal
    from app.models import ProcessedCollectionItem

    with SessionLocal.begin() as db:
        db.execute(
            delete(ProcessedCollectionItem).where(
                ProcessedCollectionItem.collection_name == name
            )
        )
        db.add_all(
            ProcessedCollectionItem(
                collection_name=name,
                item_id=_collection_item_id(name, index, item),
                sort_order=index,
                payload_json=copy.deepcopy(item),
            )
            for index, item in enumerate(items)
        )


def _postgres_collection_counts() -> tuple[dict[str, int], str | None]:
    from app.db import SessionLocal
    from app.models import ProcessedCollectionItem

    try:
        with SessionLocal() as db:
            rows = db.execute(
                select(
                    ProcessedCollectionItem.collection_name,
                    func.count(ProcessedCollectionItem.id),
                ).group_by(ProcessedCollectionItem.collection_name)
            ).all()
            return {str(name): int(count) for name, count in rows}, None
    except Exception as exc:  # pragma: no cover - exact database failures vary by environment
        return {}, str(exc)


def _collection_item_id(name: str, index: int, item: dict[str, Any]) -> str:
    if name in SINGLETON_COLLECTIONS:
        return "latest"
    for key in ("public_id", "id", "source_record_id", "key"):
        value = item.get(key)
        if value:
            return str(value)[:255]
    return f"{name}-{index}"


def _require_collection(name: str, allowed: tuple[str, ...]) -> None:
    if name not in allowed:
        raise ValueError(f"Unsupported processed collection for this operation: {name}")
