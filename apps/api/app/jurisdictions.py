from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

JURISDICTION_DIR = Path(__file__).parent / "jurisdictions"


class SourceConfig(BaseModel):
    key: str
    name: str
    connector_type: Literal["arcgis", "agenda_archive", "static_geojson"]
    parser_key: str
    source_url: str
    active: bool = True
    privacy_review: str
    safety_review: str
    config: dict[str, Any] = Field(default_factory=dict)


class JurisdictionConfig(BaseModel):
    id: str
    name: str
    state: str
    country: str = "US"
    timezone: str
    default_center: tuple[float, float]
    sources: list[SourceConfig]


class ConnectorHealth(BaseModel):
    key: str
    name: str
    jurisdiction_id: str
    jurisdiction_name: str
    connector_type: str
    parser_key: str
    source_url: str
    active: bool
    status: str
    records_seen: int = 0
    records_created: int = 0
    error_count: int = 0
    last_checked_at: str | None = None
    privacy_review: str
    safety_review: str


@lru_cache
def load_jurisdictions() -> tuple[JurisdictionConfig, ...]:
    configs: list[JurisdictionConfig] = []
    for path in sorted(JURISDICTION_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        configs.append(JurisdictionConfig.model_validate(payload))
    return tuple(configs)


def list_jurisdictions() -> list[JurisdictionConfig]:
    return list(load_jurisdictions())


def active_sources() -> list[tuple[JurisdictionConfig, SourceConfig]]:
    pairs: list[tuple[JurisdictionConfig, SourceConfig]] = []
    for jurisdiction in load_jurisdictions():
        for source in jurisdiction.sources:
            if source.active:
                pairs.append((jurisdiction, source))
    return pairs


def connector_health(source_health: dict[str, Any]) -> list[ConnectorHealth]:
    latest_by_key = {
        source.get("key"): source
        for source in source_health.get("sources", [])
        if isinstance(source, dict)
    }
    rows: list[ConnectorHealth] = []
    for jurisdiction, source in active_sources():
        latest = latest_by_key.get(source.key) or {}
        rows.append(
            ConnectorHealth(
                key=source.key,
                name=source.name,
                jurisdiction_id=jurisdiction.id,
                jurisdiction_name=jurisdiction.name,
                connector_type=source.connector_type,
                parser_key=source.parser_key,
                source_url=source.source_url,
                active=source.active,
                status=str(latest.get("status") or "not_run"),
                records_seen=int(latest.get("records_seen") or 0),
                records_created=int(latest.get("records_created") or 0),
                error_count=int(latest.get("error_count") or 0),
                last_checked_at=latest.get("checked_at"),
                privacy_review=source.privacy_review,
                safety_review=source.safety_review,
            )
        )
    return rows
