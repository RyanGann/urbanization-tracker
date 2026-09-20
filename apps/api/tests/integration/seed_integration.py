from __future__ import annotations

import json
import os
from pathlib import Path

from app.processed_store import write_processed_list, write_processed_payload


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
        raise RuntimeError(f"PostGIS geometry validation failed for feature indexes: {invalid[:10]}")
    print(json.dumps({"postgis_geometry_valid": len(geometries)}))


def main() -> None:
    fixture_path = Path(os.environ.get("INTEGRATION_FIXTURE_PATH", "/integration/fixture.json"))
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if os.environ.get("P01_VALIDATE_GEOMETRY") == "1":
        validate_with_postgis(fixture)
    if os.environ.get("INTEGRATION_PRESERVE_IDS") != "1":
        record = fixture["development_records"][0]
        record["public_id"] = os.environ["INTEGRATION_FIXTURE_ID"]
        record["title"] = os.environ["INTEGRATION_FIXTURE_TITLE"]
    write_processed_list("development_records", fixture["development_records"])
    write_processed_list("staged_development_records", [])
    write_processed_list("environmental_overlays", fixture["environmental_overlays"])
    write_processed_payload("source_health", fixture["source_health"])


if __name__ == "__main__":
    main()
