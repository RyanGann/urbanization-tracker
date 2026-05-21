from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import get_settings
from app.jurisdictions import ConnectorHealth, connector_health
from app.seed_store import load_source_health


def build_source_health_monitor(
    *,
    source_health: dict[str, Any] | None = None,
    health_rows: Iterable[ConnectorHealth] | None = None,
    max_age_hours: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    checked_at = now or datetime.now(UTC)
    max_age = max_age_hours or settings.source_health_max_age_hours
    rows = list(
        health_rows
        if health_rows is not None
        else connector_health(source_health if source_health is not None else load_source_health())
    )
    source_checks = [
        _source_check(row=row, max_age_hours=max_age, now=checked_at) for row in rows
    ]
    failing_count = sum(1 for source in source_checks if not source["healthy"])
    return {
        "status": "healthy" if failing_count == 0 else "degraded",
        "checked_at": checked_at.isoformat(),
        "max_age_hours": max_age,
        "sources_total": len(source_checks),
        "sources_healthy": len(source_checks) - failing_count,
        "sources_failing": failing_count,
        "sources": sorted(source_checks, key=lambda source: str(source["key"])),
    }


def _source_check(
    *,
    row: ConnectorHealth,
    max_age_hours: int,
    now: datetime,
) -> dict[str, Any]:
    issues: list[str] = []
    last_checked_at = _parse_datetime(row.last_checked_at)
    age_hours: float | None = None

    if row.status == "not_run":
        issues.append("not_run")
    elif row.status not in {"healthy"}:
        issues.append(f"status:{row.status}")

    if row.error_count:
        issues.append(f"errors:{row.error_count}")

    if row.last_checked_at is None:
        issues.append("missing_checked_at")
    elif last_checked_at is None:
        issues.append("invalid_checked_at")
    else:
        age_hours = round((now - last_checked_at).total_seconds() / 3600, 2)
        if now - last_checked_at > timedelta(hours=max_age_hours):
            issues.append(f"stale:{age_hours}h")

    return {
        "key": row.key,
        "name": row.name,
        "jurisdiction_id": row.jurisdiction_id,
        "jurisdiction_name": row.jurisdiction_name,
        "status": row.status,
        "healthy": not issues,
        "issues": issues,
        "records_seen": row.records_seen,
        "records_created": row.records_created,
        "error_count": row.error_count,
        "last_checked_at": row.last_checked_at,
        "age_hours": age_hours,
    }


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
