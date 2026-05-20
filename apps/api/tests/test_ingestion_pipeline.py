import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from app.ingestion.connectors.arcgis import ArcGISRestConnector
from app.ingestion.pipeline import ingest_madison_county


def test_madison_county_ingestion_preserves_other_processed_sources(tmp_path: Path) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir(parents=True)
    (processed_dir / "development_records.json").write_text(
        json.dumps(
            [
                {
                    "public_id": "existing-huntsville-record",
                    "source_url": "https://example.test/huntsville-source",
                    "proximity_flags": [{"flag_type": "wetland"}],
                }
            ]
        ),
        encoding="utf-8",
    )
    (processed_dir / "staged_development_records.json").write_text(
        json.dumps(
            [
                {
                    "id": "stage-existing-huntsville-record",
                    "source_url": "https://example.test/huntsville-source",
                }
            ]
        ),
        encoding="utf-8",
    )
    (processed_dir / "raw_records.json").write_text(
        json.dumps(
            [
                {
                    "data_source_key": "huntsville_new_subdivisions",
                    "source_record_id": "1",
                }
            ]
        ),
        encoding="utf-8",
    )
    (processed_dir / "source_health.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "key": "huntsville_new_subdivisions",
                        "status": "healthy",
                        "error_count": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with ArcGISRestConnector(transport=httpx.MockTransport(_madison_arcgis_handler)) as connector:
        health = ingest_madison_county(
            data_dir=tmp_path,
            record_limit=1,
            connector=connector,
        )

    records = json.loads((processed_dir / "development_records.json").read_text())
    keys = {record["public_id"] for record in records}
    health_keys = {source["key"] for source in health["sources"]}

    assert "existing-huntsville-record" in keys
    assert "madison-county-subdivision-95-7-abernathy-estates" in keys
    assert health["records"]["published"] == 2
    assert health["records"]["proximity_flags"] == 1
    assert {"huntsville_new_subdivisions", "madison_county_subdivisions"} <= health_keys


def _madison_arcgis_handler(request: httpx.Request) -> httpx.Response:
    parsed = urlparse(str(request.url))
    params = {key: values[0] for key, values in parse_qs(parsed.query).items()}

    if parsed.path.endswith("/0") and params.get("f") == "json":
        return httpx.Response(
            200,
            json={
                "currentVersion": 11.3,
                "geometryType": "esriGeometryPolygon",
                "supportedQueryFormats": "JSON, geoJSON",
            },
        )

    if params.get("returnCountOnly") == "true":
        return httpx.Response(200, json={"count": 1})

    return httpx.Response(
        200,
        json={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "OBJECTID": 7,
                        "Subd_ID": 95,
                        "Subd_Name": "Abernathy Estates",
                        "Parcels": "8",
                        "YearFiled": 1987,
                        "DateFiled": "6/24/1987",
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-86.72, 34.72],
                                [-86.71, 34.72],
                                [-86.71, 34.73],
                                [-86.72, 34.73],
                                [-86.72, 34.72],
                            ]
                        ],
                    },
                }
            ],
            "exceededTransferLimit": False,
        },
    )
