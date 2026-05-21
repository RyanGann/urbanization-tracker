from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat()


def ensure_data_dirs(data_dir: Path) -> None:
    for child in ["raw", "processed", "runs"]:
        (data_dir / child).mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def append_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, sort_keys=True))
            handle.write("\n")


def list_artifact_manifest(data_dir: Path) -> list[dict[str, Any]]:
    payload = read_json(_artifact_manifest_path(data_dir), [])
    if not isinstance(payload, list):
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def record_artifact(
    *,
    data_dir: Path,
    path: Path,
    artifact_type: str,
    source_key: str,
    run_id: str | None = None,
    source_url: str | None = None,
    content_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    relative_path = _relative_artifact_path(data_dir, path)
    entry: dict[str, Any] = {
        "id": _artifact_id(source_key, artifact_type, relative_path),
        "artifact_type": artifact_type,
        "source_key": source_key,
        "local_path": relative_path,
        "storage_uri": _artifact_storage_uri(data_dir, relative_path),
        "byte_size": path.stat().st_size,
        "sha256": _file_sha256(path),
        "recorded_at": iso_now(),
    }
    if run_id:
        entry["run_id"] = run_id
    if source_url:
        entry["source_url"] = source_url
    if content_type:
        entry["content_type"] = content_type
    if metadata:
        entry["metadata"] = metadata

    manifest = list_artifact_manifest(data_dir)
    manifest_by_id = {str(item["id"]): item for item in manifest if item.get("id")}
    manifest_by_id[str(entry["id"])] = entry
    write_json(
        _artifact_manifest_path(data_dir),
        sorted(manifest_by_id.values(), key=lambda item: str(item["local_path"])),
    )
    return entry


def _artifact_manifest_path(data_dir: Path) -> Path:
    return data_dir / "processed" / "artifact_manifest.json"


def _artifact_storage_uri(data_dir: Path, relative_path: str) -> str:
    base_uri = get_settings().artifact_storage_base_uri
    if base_uri:
        return f"{base_uri.rstrip('/')}/{relative_path}"
    return str(data_dir / relative_path)


def _relative_artifact_path(data_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(data_dir.resolve()).as_posix()


def _artifact_id(source_key: str, artifact_type: str, relative_path: str) -> str:
    safe_bits = f"{source_key}:{artifact_type}:{relative_path}"
    return _json_sha256(safe_bits)[:24]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
