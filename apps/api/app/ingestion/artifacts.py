from __future__ import annotations

import hashlib
import importlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, cast

from app.config import get_settings
from app.ingestion.artifact_sink import ArtifactError


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


def write_staged_json(data_dir: Path, path: Path, payload: Any) -> None:
    write_staged_bytes(
        data_dir, path, json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    )


def write_staged_bytes(data_dir: Path, path: Path, payload: bytes) -> None:
    """Enforce the local raw/text cache budget before creating a payload file.

    The budget is deliberately conservative for atomic replacement: the old
    file and new temporary file both count until the replacement completes.
    Metadata manifests and run summaries are not source-payload staging.
    """
    if not get_settings().artifact_durability_required:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return
    root = data_dir.resolve()
    target = path.resolve()
    staging_roots = (root / "raw", root / "processed" / "source_documents")
    if not target.is_relative_to(root) or not any(
        target.is_relative_to(stage_root) for stage_root in staging_roots
    ):
        raise ArtifactError("artifact_path")
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root):
        raise ArtifactError("artifact_path")
    with staging_budget_lock(root):
        used = 0
        for stage_root in staging_roots:
            if not stage_root.exists():
                continue
            for staged in stage_root.rglob("*"):
                if staged.is_symlink():
                    raise ArtifactError("artifact_path")
                if staged.is_file():
                    used += staged.stat().st_size
        if used + len(payload) > get_settings().artifact_staging_max_bytes:
            raise ArtifactError("artifact_too_large")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as temp:
                temporary_path = Path(temp.name)
                temp.write(payload)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


@contextmanager
def staging_budget_lock(root: Path) -> Iterator[None]:
    """Serialize the scan and write across workers sharing a staging root."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".artifact-staging.lock").open("a+b") as handle:
        windows_lock: Any = None
        if os.name == "nt":
            windows_lock = cast(Any, importlib.import_module("msvcrt"))

            handle.seek(0)
            if not handle.read(1):
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            windows_lock.locking(handle.fileno(), windows_lock.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                windows_lock.locking(handle.fileno(), windows_lock.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, sort_keys=True))
            handle.write("\n")


def list_artifact_manifest(data_dir: Path) -> list[dict[str, Any]]:
    try:
        payload = read_json(_artifact_manifest_path(data_dir), [])
    except json.JSONDecodeError:
        return []
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
