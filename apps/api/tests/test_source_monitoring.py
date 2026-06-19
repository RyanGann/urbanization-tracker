from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.jurisdictions import ConnectorHealth
from app.main import app
from app.source_monitoring import build_source_health_monitor

client = TestClient(app)


def test_source_health_monitor_passes_for_fresh_healthy_sources() -> None:
    now = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
    payload = build_source_health_monitor(
        health_rows=[
            _health_row(
                key="huntsville_new_subdivisions",
                status="healthy",
                last_checked_at=(now - timedelta(hours=2)).isoformat(),
                records_seen=12,
                records_created=12,
            )
        ],
        max_age_hours=48,
        now=now,
    )

    assert payload["status"] == "healthy"
    assert payload["sources_failing"] == 0
    assert payload["sources"][0]["healthy"] is True
    assert payload["sources"][0]["age_hours"] == 2.0


def test_source_health_monitor_marks_stale_sources_degraded() -> None:
    now = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
    payload = build_source_health_monitor(
        health_rows=[
            _health_row(
                key="huntsville_new_subdivisions",
                status="healthy",
                last_checked_at=(now - timedelta(hours=49)).isoformat(),
            )
        ],
        max_age_hours=48,
        now=now,
    )

    assert payload["status"] == "degraded"
    assert payload["sources_failing"] == 1
    assert "stale:49.0h" in payload["sources"][0]["issues"]


def test_source_health_monitor_preserves_zero_hour_override() -> None:
    now = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
    payload = build_source_health_monitor(
        health_rows=[
            _health_row(
                key="huntsville_new_subdivisions",
                status="healthy",
                last_checked_at=(now - timedelta(minutes=1)).isoformat(),
            )
        ],
        max_age_hours=0,
        now=now,
    )

    assert payload["max_age_hours"] == 0
    assert payload["status"] == "degraded"
    assert "stale:0.02h" in payload["sources"][0]["issues"]


def test_source_health_monitor_marks_errors_degraded() -> None:
    now = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
    payload = build_source_health_monitor(
        health_rows=[
            _health_row(
                key="huntsville_new_subdivisions",
                status="failing",
                last_checked_at=now.isoformat(),
                error_count=1,
            )
        ],
        max_age_hours=48,
        now=now,
    )

    assert payload["status"] == "degraded"
    assert {"status:failing", "errors:1"} <= set(payload["sources"][0]["issues"])


def test_source_health_endpoint_returns_503_when_sources_have_not_run() -> None:
    response = client.get("/health/source-health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["sources_failing"] > 0
    assert any("not_run" in source["issues"] for source in body["sources"])


def _health_row(
    *,
    key: str,
    status: str,
    last_checked_at: str | None,
    records_seen: int = 0,
    records_created: int = 0,
    error_count: int = 0,
) -> ConnectorHealth:
    return ConnectorHealth(
        key=key,
        name="Test Source",
        jurisdiction_id="test-jurisdiction",
        jurisdiction_name="Test Jurisdiction",
        connector_type="arcgis",
        parser_key="test_parser",
        source_url="https://example.test/source",
        active=True,
        status=status,
        records_seen=records_seen,
        records_created=records_created,
        error_count=error_count,
        last_checked_at=last_checked_at,
        privacy_review="Reviewed",
        safety_review="Reviewed",
    )
