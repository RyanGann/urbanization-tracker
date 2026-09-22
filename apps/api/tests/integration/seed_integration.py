from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic, sleep

from app.map_layer_catalog import (
    backfill_map_layer_catalog,
    catalog_revision,
    upgrade_map_layer_catalog,
)
from app.processed_store import (
    read_processed_payload,
    write_processed_list,
    write_processed_payload,
)


def validate_with_postgis(fixture: dict) -> None:
    from sqlalchemy import text

    from app.db import SessionLocal

    geometries = [
        record["geometry"]
        for record in fixture.get("development_records", [])
        if record.get("geometry")
    ]
    geometries.extend(
        feature["geometry"]
        for overlay in fixture.get("environmental_overlays", [])
        for feature in overlay.get("features", {}).get("features", [])
        if feature.get("geometry")
    )
    invalid: list[int] = []
    with SessionLocal() as db:
        for index, geometry in enumerate(geometries):
            valid = db.scalar(
                text("SELECT ST_IsValid(ST_GeomFromGeoJSON(:geometry))"),
                {"geometry": json.dumps(geometry)},
            )
            if not valid:
                invalid.append(index)
    if invalid:
        raise RuntimeError(
            f"PostGIS geometry validation failed for feature indexes: {invalid[:10]}"
        )
    quarantined = fixture.get("fixture_diagnostics", {}).get("quarantined_invalid", [])
    quarantined_invalid_checked = False
    if quarantined:
        with SessionLocal() as db:
            diagnostic_valid = db.scalar(
                text("SELECT ST_IsValid(ST_GeomFromGeoJSON(:geometry))"),
                {"geometry": json.dumps(quarantined[0]["geometry"])},
            )
        if diagnostic_valid is not False:
            raise RuntimeError(
                "P01 quarantined invalid diagnostic unexpectedly passed PostGIS validity"
            )
        quarantined_invalid_checked = True
    print(json.dumps({
        "postgis_geometry_valid": len(geometries),
        "postgis_quarantined_invalid": quarantined_invalid_checked,
    }))


def main() -> None:
    fixture_path = Path(os.environ.get("INTEGRATION_FIXTURE_PATH", "/integration/fixture.json"))
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if os.environ.get("P01_VALIDATE_GEOMETRY") == "1":
        validate_with_postgis(fixture)
    if os.environ.get("INTEGRATION_PRESERVE_IDS") != "1":
        record = fixture["development_records"][0]
        record["public_id"] = os.environ["INTEGRATION_FIXTURE_ID"]
        record["title"] = os.environ["INTEGRATION_FIXTURE_TITLE"]
    if read_processed_payload("map_layer_catalog") is None:
        assert upgrade_map_layer_catalog() == {"status": "uninitialized"}
        write_processed_payload("source_health", {"status": "failed", "sources": []})
        assert upgrade_map_layer_catalog() == {"status": "uninitialized"}
    write_processed_list("development_records", fixture["development_records"])
    write_processed_list("staged_development_records", [])
    write_processed_list("environmental_overlays", fixture["environmental_overlays"])
    write_processed_payload("source_health", fixture["source_health"])
    # Exercise the actual idempotent release upgrade against the isolated Postgres
    # store before bringing up the API. No geometry is transferred by this step.
    if fixture["environmental_overlays"]:
        assert upgrade_map_layer_catalog()["status"] in {"created", "preserved"}
    else:
        # Explicit fixture initialization distinguishes known empty from absent
        # legacy overlay rows, which have no per-collection readiness marker.
        backfill_map_layer_catalog()
    persisted = read_processed_payload("map_layer_catalog")
    assert persisted is not None
    assert upgrade_map_layer_catalog() == {"status": "preserved"}
    assert read_processed_payload("map_layer_catalog") == persisted
    if persisted["layers"]:
        # A later ready tile catalog must survive an upgrade unchanged as well.
        ready = json.loads(json.dumps(persisted))
        ready["layers"][0].update({
            "delivery_status": "ready",
            "tile_url": "/api/map/tiles/example/{z}/{x}/{y}.pbf",
            "source_layer": "context",
        })
        ready["catalog_revision"] = catalog_revision({
            "data_mode": ready["data_mode"], "layers": ready["layers"],
        })
        write_processed_payload("map_layer_catalog", ready)
        assert upgrade_map_layer_catalog() == {"status": "preserved"}
        assert read_processed_payload("map_layer_catalog") == ready
        write_processed_payload("map_layer_catalog", persisted)
    print(json.dumps({"catalog_upgrade": "created_or_preserved", "idempotence": "passed"}))
    assert_catalog_writer_serialization(persisted)


def assert_catalog_writer_serialization(payload: dict) -> None:
    from sqlalchemy import text

    from app.db import SessionLocal
    from app.transactional_store import (
        CANONICAL_MUTATION_LOCK_KEY,
        CANONICAL_MUTATION_LOCK_NAMESPACE,
        CollectionUnitOfWork,
    )

    started = Event()

    def publish_catalog() -> None:
        started.set()
        write_processed_payload("map_layer_catalog", payload)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with SessionLocal.begin() as session:
            with CollectionUnitOfWork(session).canonical_mutation():
                publishing = pool.submit(publish_catalog)
                assert started.wait(timeout=2)
                deadline = monotonic() + 1
                while monotonic() < deadline:
                    waiting = session.scalar(text("""
                        SELECT count(*) FROM pg_locks
                        WHERE locktype = 'advisory' AND NOT granted
                          AND classid = :namespace AND objid = :key
                    """), {
                        "namespace": CANONICAL_MUTATION_LOCK_NAMESPACE,
                        "key": CANONICAL_MUTATION_LOCK_KEY,
                    })
                    if waiting:
                        break
                    sleep(0.02)
                else:
                    raise AssertionError("Catalog writer bypassed the shared mutation lock")
                assert not publishing.done()
        publishing.result(timeout=5)
    assert upgrade_map_layer_catalog() == {"status": "preserved"}
    assert read_processed_payload("map_layer_catalog") == payload
    print(json.dumps({"catalog_writer_serialization": "passed"}))


if __name__ == "__main__":
    main()
