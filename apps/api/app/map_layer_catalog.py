from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from app.config import get_settings
from app.data_availability import Availability, DataUnavailableError
from app.processed_store import (
    read_processed_list_result,
    read_processed_payload_result,
    write_processed_payload,
)
from app.schemas import MapLayerCatalog

CATALOG_COLLECTION = "map_layer_catalog"
DEMO_CATALOG_PATH = Path(__file__).parent / "seed" / "map_layer_catalog.json"


def catalog_revision(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _coverage_status(
    source_status: str, reported_count: Any, fetched_count: Any
) -> str:
    if source_status != "healthy":
        return "failed"
    if (
        isinstance(reported_count, int)
        and not isinstance(reported_count, bool)
        and isinstance(fetched_count, int)
        and not isinstance(fetched_count, bool)
        and reported_count > fetched_count
    ):
        return "partial"
    # A source count does not prove the declared scope is complete. D01 owns
    # scope reconciliation, so equality and absent counts stay explicitly unknown.
    return "unknown"


def build_catalog(
    environmental_sources: list[tuple[Any, dict[str, Any]]],
    *,
    data_mode: str = "live",
) -> dict[str, Any]:
    layers: list[dict[str, Any]] = []
    for config, health in environmental_sources:
        raw_metadata = health.get("metadata")
        metadata: dict[str, Any] = (
            raw_metadata if isinstance(raw_metadata, dict) else {}
        )
        source_status = str(health.get("status", "unknown"))
        reported_count = metadata.get("reported_count")
        fetched_count = health.get("records_seen")
        layers.append(
            {
                "id": str(config.key),
                "kind": "vector",
                "title": str(config.name),
                "category": str(config.category or "context"),
                "data_version": health.get("raw_artifact_sha256"),
                "display_version": None,
                "delivery_status": "processing" if source_status == "healthy" else "failed",
                "tile_url": None,
                "source_layer": None,
                "minzoom": None,
                "maxzoom": None,
                "bounds": None,
                "coverage": {
                    "status": _coverage_status(
                        source_status, reported_count, fetched_count
                    ),
                    "scope_id": None,
                    "reported_count": reported_count,
                    "fetched_count": fetched_count,
                },
                "source_name": str(config.source_agency),
                "source_url": str(config.layer_url),
                "attribution": str(config.attribution),
                "caveat": str(config.caveat or ""),
                "data_as_of": None,
                "fetched_at": health.get("checked_at"),
                "default_visible": bool(config.default_visible),
            }
        )
    payload: dict[str, Any] = {"data_mode": data_mode, "catalog_revision": "", "layers": layers}
    payload["catalog_revision"] = catalog_revision({"data_mode": data_mode, "layers": layers})
    return payload


def backfill_map_layer_catalog() -> MapLayerCatalog:
    """Offline compatibility backfill; this is intentionally allowed to read bulk overlays."""
    result = read_processed_list_result("environmental_overlays")
    overlays = result.require_ready(collection="environmental_overlays")
    layers: list[dict[str, Any]] = []
    for overlay in overlays:
        feature_count = len(overlay.get("features", {}).get("features", []))
        layers.append({
            "id": overlay["id"], "kind": "vector", "title": overlay["name"],
            "category": overlay["category"], "data_version": None, "display_version": None,
            "delivery_status": "processing", "tile_url": None, "source_layer": None,
            "minzoom": None, "maxzoom": None, "bounds": None,
            "coverage": {"status": "unknown", "scope_id": None, "reported_count": None,
                         "fetched_count": feature_count},
            "source_name": overlay["attribution"], "source_url": overlay["source_url"],
            "attribution": overlay["attribution"], "caveat": overlay["caveat"],
            "data_as_of": None, "fetched_at": None, "default_visible": True,
        })
    payload = {"data_mode": "live", "catalog_revision": "", "layers": layers}
    payload["catalog_revision"] = catalog_revision({"data_mode": "live", "layers": layers})
    catalog = MapLayerCatalog.model_validate(payload)
    write_processed_payload(CATALOG_COLLECTION, catalog.model_dump(mode="json"))
    return catalog

def _load_demo_catalog() -> dict[str, Any]:
    payload = json.loads(DEMO_CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DataUnavailableError(
            collection=CATALOG_COLLECTION, availability=Availability.UNAVAILABLE
        )
    return cast(dict[str, Any], payload)


def load_map_layer_catalog() -> MapLayerCatalog:
    if get_settings().data_mode == "demo":
        payload = _load_demo_catalog()
    else:
        result = read_processed_payload_result(CATALOG_COLLECTION)
        payload = result.require_ready(collection=CATALOG_COLLECTION)
    if not isinstance(payload, dict):
        raise DataUnavailableError(
            collection=CATALOG_COLLECTION, availability=Availability.UNAVAILABLE
        )
    if payload.get("data_mode") != get_settings().data_mode:
        raise DataUnavailableError(
            collection=CATALOG_COLLECTION, availability=Availability.UNAVAILABLE
        )
    try:
        catalog = MapLayerCatalog.model_validate(copy.deepcopy(payload))
    except ValidationError as exc:
        raise DataUnavailableError(
            collection=CATALOG_COLLECTION, availability=Availability.UNAVAILABLE
        ) from exc
    expected_revision = catalog_revision(
        {
            "data_mode": catalog.data_mode,
            "layers": [layer.model_dump(mode="json") for layer in catalog.layers],
        }
    )
    if catalog.catalog_revision != expected_revision:
        raise DataUnavailableError(
            collection=CATALOG_COLLECTION, availability=Availability.UNAVAILABLE
        )
    return catalog
