"""Operator-only shadow bridge; no activation, catalog promotion or rights gate."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from app.ingestion.artifact_service import ArtifactService
from app.ingestion.artifacts import staging_budget_lock
from app.ingestion.environmental_attestation import attest_prepared, import_and_validate
from app.ingestion.environmental_proof import ProvenanceError, prepare_observation
from app.ingestion.scoped_arcgis import _digest


def bridge_environmental_observation(
    service: ArtifactService,
    source_key: str,
    run_id: str,
    workspace: Path,
) -> dict[str, Any]:
    root = service.settings.ingestion_data_dir.resolve()
    target = workspace.resolve()
    if not target.is_relative_to(root / "raw") or target.exists():
        raise ProvenanceError("bridge_workspace_invalid")
    if any(parent.is_symlink() for parent in (workspace, *workspace.parents) if parent != root):
        raise ProvenanceError("bridge_workspace_invalid")
    # Use O01's filesystem quota lock, never the C02 database mutation lock.
    with staging_budget_lock(root):
        started, used, files = time.monotonic(), 0, 0
        for directory in (root / "raw", root / "processed" / "source_documents"):
            for path in directory.rglob("*"):
                files += 1
                if path.is_symlink():
                    raise ProvenanceError("bridge_workspace_invalid")
                if files > 100_000 or time.monotonic() - started > 30:
                    raise ProvenanceError("bridge_staging_scan_budget")
                if path.is_file():
                    used += path.stat().st_size
        remaining = service.settings.artifact_staging_max_bytes - used
        if remaining <= 0:
            raise ProvenanceError("bridge_staging_budget")
        observation = prepare_observation(
            service, source_key, run_id, target, max_staged_bytes=remaining
        )
    prepared = import_and_validate(service, observation)
    identity = attest_prepared(service, prepared)
    return {
        "status": "attested_shadow",
        "attestation_id": str(identity),
        "source_key": source_key,
        "run_id": run_id,
        "layer_id": prepared.layer_id,
        "data_version": prepared.layer["data_version"],
        "input_sha256": observation.canonical_sha256,
        "proof_sha256": _digest(prepared.binding(service.sink_id)),
    }
