import json
from urllib.parse import parse_qs, urlparse

import httpx

from app.ingestion.connectors.arcgis import ArcGISLayerConfig, ArcGISRestConnector


def test_arcgis_connector_paginates_geojson() -> None:
    requests: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        parsed = urlparse(str(request.url))
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        requests.append(params)

        if parsed.path.endswith("/0") and params.get("f") == "json":
            return httpx.Response(
                200,
                json={
                    "geometryType": "esriGeometryPolygon",
                    "supportedQueryFormats": "JSON, geoJSON",
                },
            )

        if params.get("returnCountOnly") == "true":
            return httpx.Response(200, json={"count": 3})

        offset = int(params.get("resultOffset", "0"))
        if offset == 0:
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        _feature(1, -86.6, 34.7),
                        _feature(2, -86.5, 34.8),
                    ],
                    "exceededTransferLimit": True,
                },
            )

        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [_feature(3, -86.4, 34.9)],
                "exceededTransferLimit": False,
            },
        )

    config = ArcGISLayerConfig(
        key="test_source",
        name="Test Source",
        service_url="https://example.test/arcgis/MapServer",
        layer_id=0,
        source_type="arcgis_mapserver",
        source_agency="Test Agency",
        attribution="Test Agency",
        geometry_type="point",
        result_record_count=2,
    )

    with ArcGISRestConnector(transport=httpx.MockTransport(handler)) as connector:
        metadata = connector.get_layer_metadata(config)
        count = connector.get_count(config)
        collection = connector.fetch_geojson(config)

    assert metadata["geometryType"] == "esriGeometryPolygon"
    assert count == 3
    assert len(collection["features"]) == 3
    assert requests[-1]["resultOffset"] == "2"
    assert requests[-1]["outSR"] == "4326"


def _feature(feature_id: int, lon: float, lat: float) -> dict[str, object]:
    return json.loads(
        json.dumps(
            {
                "type": "Feature",
                "properties": {"OBJECTID": feature_id},
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            }
        )
    )
