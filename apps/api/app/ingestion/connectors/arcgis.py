from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx


class ArcGISError(RuntimeError):
    """Raised when an ArcGIS REST service returns an unusable response."""


@dataclass(frozen=True)
class ArcGISLayerConfig:
    key: str
    name: str
    service_url: str
    layer_id: int
    source_type: str
    source_agency: str
    attribution: str
    geometry_type: str
    where: str = "1=1"
    out_fields: tuple[str, ...] = ("*",)
    order_by_fields: str | None = None
    result_record_count: int = 2000
    max_records: int | None = None
    source_srid: int = 102629
    canonical_srid: int = 4326
    license_notes: str | None = None
    category: str | None = None
    caveat: str | None = None
    connector_config: Mapping[str, Any] = field(default_factory=dict)

    @property
    def layer_url(self) -> str:
        return f"{self.service_url.rstrip('/')}/{self.layer_id}"

    @property
    def query_url(self) -> str:
        return f"{self.layer_url}/query"


class ArcGISRestConnector:
    def __init__(self, timeout: float = 30.0, transport: httpx.BaseTransport | None = None) -> None:
        self.client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> ArcGISRestConnector:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get_layer_metadata(self, config: ArcGISLayerConfig) -> dict[str, Any]:
        response = self.client.get(config.layer_url, params={"f": "json"})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ArcGISError(f"{config.key} returned non-object metadata")
        self._raise_for_arcgis_error(payload, config)
        return payload

    def get_count(self, config: ArcGISLayerConfig) -> int:
        response = self.client.get(
            config.query_url,
            params={
                "f": "json",
                "where": config.where,
                "returnGeometry": "false",
                "returnCountOnly": "true",
            },
        )
        response.raise_for_status()
        payload = response.json()
        self._raise_for_arcgis_error(payload, config)
        return int(payload.get("count", 0))

    def fetch_geojson(self, config: ArcGISLayerConfig) -> dict[str, Any]:
        features: list[dict[str, Any]] = []
        offset = 0
        page_size = config.result_record_count
        records_remaining = config.max_records

        while True:
            page_count = page_size
            if records_remaining is not None:
                page_count = min(page_count, records_remaining)
                if page_count <= 0:
                    break

            response = self.client.get(
                config.query_url,
                params=self._query_params(config, offset=offset, page_count=page_count),
            )
            response.raise_for_status()
            payload = response.json()
            self._raise_for_arcgis_error(payload, config)

            page_features = payload.get("features", [])
            if not isinstance(page_features, list):
                raise ArcGISError(f"{config.key} returned non-list GeoJSON features")

            features.extend(page_features)
            fetched = len(page_features)
            if records_remaining is not None:
                records_remaining -= fetched

            exceeded = bool(payload.get("exceededTransferLimit"))
            if fetched < page_count or not exceeded:
                break
            offset += fetched

        return {
            "type": "FeatureCollection",
            "features": features,
            "source": {
                "key": config.key,
                "name": config.name,
                "layer_url": config.layer_url,
                "source_srid": config.source_srid,
                "canonical_srid": config.canonical_srid,
            },
        }

    def _query_params(
        self, config: ArcGISLayerConfig, *, offset: int, page_count: int
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "f": "geojson",
            "where": config.where,
            "outFields": ",".join(config.out_fields),
            "outSR": str(config.canonical_srid),
            "returnGeometry": "true",
            "resultOffset": str(offset),
            "resultRecordCount": str(page_count),
        }
        if config.order_by_fields:
            params["orderByFields"] = config.order_by_fields
        return params

    def _raise_for_arcgis_error(
        self, payload: Mapping[str, Any], config: ArcGISLayerConfig
    ) -> None:
        error = payload.get("error")
        if isinstance(error, Mapping):
            message = error.get("message") or error
            raise ArcGISError(f"{config.key} ArcGIS error: {message}")
