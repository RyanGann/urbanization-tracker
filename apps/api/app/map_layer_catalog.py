from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import text

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


def _coverage_status(source_status: str, reported_count: Any, fetched_count: Any) -> str:
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
        metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
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
                    "status": _coverage_status(source_status, reported_count, fetched_count),
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


def merge_ingestion_catalog(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Reconcile source observations without replacing a ready delivery version.

    This is pure so the ingestion adapter can invoke it inside its existing C02
    unit of work. P03 owns any after-transaction import bridge.
    """
    incoming_model = MapLayerCatalog.model_validate(copy.deepcopy(incoming))
    incoming_payload = incoming_model.model_dump(mode="json")
    if existing is None:
        result = incoming_payload
        if "imports" in incoming:
            result["imports"] = copy.deepcopy(incoming["imports"])
    else:
        existing_model = MapLayerCatalog.model_validate(copy.deepcopy(existing))
        if existing_model.data_mode != incoming_model.data_mode:
            raise ValueError("Cannot merge map layer catalogs from different data modes")
        expected_revision = catalog_revision(
            {
                "data_mode": existing_model.data_mode,
                "layers": [layer.model_dump(mode="json") for layer in existing_model.layers],
            }
        )
        if existing_model.catalog_revision != expected_revision:
            raise ValueError("Existing map layer catalog revision is invalid")
        existing_by_id = {
            str(layer["id"]): layer for layer in existing_model.model_dump(mode="json")["layers"]
        }
        incoming_by_id = {str(layer["id"]): layer for layer in incoming_payload["layers"]}
        layers: list[dict[str, Any]] = []
        for layer_id, old_layer in existing_by_id.items():
            replacement = incoming_by_id.pop(layer_id, old_layer)
            layers.append(old_layer if old_layer["delivery_status"] == "ready" else replacement)
        layers.extend(incoming_by_id.values())
        result = {
            "data_mode": incoming_payload["data_mode"],
            "catalog_revision": "",
            "layers": layers,
        }
        if "imports" in existing:
            result["imports"] = copy.deepcopy(existing["imports"])
        elif "imports" in incoming:
            result["imports"] = copy.deepcopy(incoming["imports"])
    result["catalog_revision"] = catalog_revision(
        {"data_mode": result["data_mode"], "layers": result["layers"]}
    )
    MapLayerCatalog.model_validate(copy.deepcopy(result))
    return result


def backfill_map_layer_catalog() -> MapLayerCatalog:
    """Offline compatibility backfill; this is intentionally allowed to read bulk overlays."""
    result = read_processed_list_result("environmental_overlays")
    overlays = result.require_ready(collection="environmental_overlays")
    catalog = _project_legacy_catalog(
        [(overlay, len(overlay["features"]["features"])) for overlay in overlays]
    )
    write_processed_payload(CATALOG_COLLECTION, catalog.model_dump(mode="json"))
    return catalog


def _project_legacy_catalog(overlays: list[tuple[dict[str, Any], int]]) -> MapLayerCatalog:
    layers: list[dict[str, Any]] = []
    for overlay, feature_count in overlays:
        layers.append(
            {
                "id": overlay["id"],
                "kind": "vector",
                "title": overlay["name"],
                "category": overlay["category"],
                "data_version": None,
                "display_version": None,
                "delivery_status": "processing",
                "tile_url": None,
                "source_layer": None,
                "minzoom": None,
                "maxzoom": None,
                "bounds": None,
                "coverage": {
                    "status": "unknown",
                    "scope_id": None,
                    "reported_count": None,
                    "fetched_count": feature_count,
                },
                "source_name": overlay["attribution"],
                "source_url": overlay["source_url"],
                "attribution": overlay["attribution"],
                "caveat": overlay["caveat"],
                "data_as_of": None,
                "fetched_at": None,
                "default_visible": True,
            }
        )
    payload = {"data_mode": "live", "catalog_revision": "", "layers": layers}
    payload["catalog_revision"] = catalog_revision({"data_mode": "live", "layers": layers})
    return MapLayerCatalog.model_validate(payload)


def upgrade_map_layer_catalog() -> dict[str, str]:
    """Idempotent release step; never fetch sources or overwrite an existing catalog."""
    settings = get_settings()
    if settings.data_mode == "demo":
        load_map_layer_catalog()
        return {"status": "demo"}
    if settings.processed_store_backend != "postgres":
        existing = read_processed_payload_result(CATALOG_COLLECTION)
        if existing.availability is not Availability.UNINITIALIZED:
            load_map_layer_catalog()  # Fail closed on malformed existing metadata.
            return {"status": "preserved"}
        overlays = read_processed_list_result("environmental_overlays")
        if overlays.availability is Availability.UNINITIALIZED:
            return {"status": "uninitialized"}
        backfill_map_layer_catalog()
        return {"status": "created"}

    from app.db import SessionLocal
    from app.transactional_store import CollectionUnitOfWork

    with SessionLocal.begin() as session:
        unit = CollectionUnitOfWork(session)
        with unit.canonical_mutation():
            # Recheck after locking; a concurrent release may already have populated it.
            existing_rows = unit.list_processed(CATALOG_COLLECTION)
            if existing_rows:
                if len(existing_rows) != 1:
                    raise ValueError("The map layer catalog must contain one singleton")
                _validate_catalog(existing_rows[0])
                return {"status": "preserved"}
            # Project on the database side: the release process never transfers or
            # materializes geometry. PostgreSQL may still inspect the stored JSONB.
            rows = session.execute(
                text("""
                SELECT payload_json::jsonb - 'features' AS metadata,
                       jsonb_array_length(
                           payload_json::jsonb #> '{features,features}'
                       ) AS feature_count
                FROM processed_collection_items
                WHERE collection_name = 'environmental_overlays'
                ORDER BY sort_order, id
            """)
            ).all()
            if not rows:
                # Empty legacy rows carry no initialization marker. Source-health
                # alone (including failed/development-only runs) cannot prove one.
                return {"status": "uninitialized"}
            if any(row.feature_count is None for row in rows):
                raise ValueError("Legacy overlay is missing its feature array")
            catalog = _project_legacy_catalog([(row.metadata, row.feature_count) for row in rows])
            unit.upsert_processed(CATALOG_COLLECTION, "latest", catalog.model_dump(mode="json"))
            return {"status": "created"}


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
    return _validate_catalog(payload)


def _validate_catalog(payload: Any) -> MapLayerCatalog:
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
