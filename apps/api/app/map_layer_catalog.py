from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config import get_settings
from app.data_availability import Availability, DataUnavailableError
from app.processed_store import read_processed_payload_result
from app.schemas import MapLayerCatalog

CATALOG_COLLECTION = "map_layer_catalog"
DEMO_CATALOG_PATH = Path(__file__).parent / "seed" / "map_layer_catalog.json"


def catalog_revision(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def build_catalog(
    environmental_sources: list[tuple[Any, dict[str, Any]]],
    *,
    data_mode: str = "live",
) -> dict[str, Any]:
    layers: list[dict[str, Any]] = []
    for config, health in environmental_sources:
        metadata = health.get("metadata") if isinstance(health.get("metadata"), dict) else {}
        source_status = str(health.get("status", "unknown"))
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
                    "status": "unknown",
                    "scope_id": None,
                    "reported_count": metadata.get("reported_count"),
                    "fetched_count": health.get("records_seen"),
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


def _load_demo_catalog() -> dict[str, Any]:
    return json.loads(DEMO_CATALOG_PATH.read_text(encoding="utf-8"))


def load_map_layer_catalog() -> MapLayerCatalog:
    if get_settings().data_mode == "demo":
        payload = _load_demo_catalog()
    else:
        result = read_processed_payload_result(CATALOG_COLLECTION)
        payload = result.require_ready(collection=CATALOG_COLLECTION)
    if payload.get("data_mode") != get_settings().data_mode:
        raise DataUnavailableError(
            collection=CATALOG_COLLECTION, availability=Availability.UNAVAILABLE
        )
    try:
        return MapLayerCatalog.model_validate(copy.deepcopy(payload))
    except ValidationError as exc:
        raise DataUnavailableError(
            collection=CATALOG_COLLECTION, availability=Availability.UNAVAILABLE
        ) from exc