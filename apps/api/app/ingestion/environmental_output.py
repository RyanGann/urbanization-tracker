"""Stage new ingestion output for shadow imports after canonical commit."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.ingestion.environmental_import import (
    ImportBusyError,
    ImportOptions,
    import_environmental_file,
)


def _coverage_and_expected(source: dict[str, Any]) -> tuple[str, int | None]:
    metadata = source.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    reported = metadata.get("reported_count")
    expected = reported if type(reported) is int and reported >= 0 else None
    fetched = metadata.get("fetched_count")
    coverage = source.get("coverage", metadata.get("coverage", "unknown"))
    if coverage not in ("failed", "partial", "unknown"):
        coverage = "unknown"
    if source.get("status") == "failing":
        coverage = "failed"
    elif (
        coverage != "failed"
        and expected is not None
        and type(fetched) is int
        and 0 <= fetched < expected
    ):
        coverage = "partial"
    return coverage, expected


def import_environmental_output(
    overlays: Iterable[dict[str, Any]], *, source_health: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Stream existing objects to transient staging; never change canonical/source health.

    Call only after the C02 transaction exits. The importer records durable progress
    and preserves ready catalog pointers. Temporary files are not durable raw evidence;
    O01 attaches separate provenance references without changing environmental version identity.
    """
    sources = {
        source["source_url"]: source
        for source in source_health
        if isinstance(source.get("source_url"), str)
    }
    reports = []
    for overlay in overlays:
        layer_id = overlay.get("id")
        safe_id = layer_id if isinstance(layer_id, str) and len(layer_id) <= 100 else None
        try:
            if not isinstance(layer_id, str):
                raise ValueError("invalid_overlay_metadata")
            source = sources.get(overlay.get("source_url"), {})
            coverage, expected = _coverage_and_expected(source)
            with TemporaryDirectory(prefix="urbanization-environment-") as directory:
                path = Path(directory) / "overlay.json"
                with path.open("w", encoding="utf-8") as target:
                    # json.dump writes encoder chunks; the wrapper holds one reference,
                    # not a second layer-sized object or serialized string.
                    json.dump([overlay], target, allow_nan=False, separators=(",", ":"))
                report = import_environmental_file(
                    path,
                    ImportOptions(
                        layer_id=layer_id,
                        scope_id=overlay.get("source_url") or layer_id,
                        scope_version="legacy-capped-v1",
                        expected_count=expected,
                        coverage=coverage,
                    ),
                    dry_run=False,
                )
            reports.append(report)
        except Exception as exc:
            reports.append(
                {
                    "layer_id": safe_id,
                    "status": "failed",
                    "code": "import_busy"
                    if isinstance(exc, ImportBusyError)
                    else "environmental_import_failed",
                }
            )
    return reports
