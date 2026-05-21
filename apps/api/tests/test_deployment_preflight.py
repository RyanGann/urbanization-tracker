from __future__ import annotations

from app.config import Settings
from app.deployment_preflight import DatabaseProbeResult, run_deployment_preflight


def production_settings(**overrides: object) -> Settings:
    values = {
        "database_url": "postgresql://tracker:secret@db.internal:5432/tracker",
        "cors_origins": "https://tracker.example.test",
        "reviewer_api_token": "reviewer-secret-token-with-length",
        "phase3_store_backend": "postgres",
        "public_base_url": "https://tracker.example.test",
        "alert_delivery_enabled": True,
        "alert_delivery_rate_limit": 25,
        "smtp_host": "smtp.example.test",
        "smtp_from_email": "alerts@example.test",
    }
    values.update(overrides)
    return Settings(**values)


def test_deployment_preflight_passes_for_production_configuration() -> None:
    result = run_deployment_preflight(
        settings=production_settings(),
        database_probe=lambda _settings: DatabaseProbeResult(
            reachable=True,
            postgis_enabled=True,
            database="tracker",
        ),
    )

    assert result["status"] == "pass"
    assert result["summary"]["failed"] == 0
    assert _status_for(result, "database_probe") == "pass"


def test_deployment_preflight_fails_for_unsafe_defaults() -> None:
    result = run_deployment_preflight(
        settings=Settings(),
        check_database=False,
    )

    assert result["status"] == "fail"
    assert _status_for(result, "reviewer_access") == "fail"
    assert _status_for(result, "phase3_store") == "fail"
    assert _status_for(result, "cors_origins") == "fail"
    assert _status_for(result, "public_base_url") == "fail"
    assert _status_for(result, "alert_delivery") == "warn"
    assert _status_for(result, "database_probe") == "skip"


def test_deployment_preflight_fails_when_alert_delivery_lacks_smtp() -> None:
    result = run_deployment_preflight(
        settings=production_settings(smtp_host=None),
        check_database=False,
    )

    assert result["status"] == "fail"
    alert_check = _check_for(result, "alert_delivery")
    assert alert_check["status"] == "fail"
    assert "SMTP_HOST" in alert_check["detail"]


def test_deployment_preflight_fails_without_postgis() -> None:
    result = run_deployment_preflight(
        settings=production_settings(),
        database_probe=lambda _settings: DatabaseProbeResult(
            reachable=True,
            postgis_enabled=False,
            database="tracker",
        ),
    )

    assert result["status"] == "fail"
    database_check = _check_for(result, "database_probe")
    assert database_check["status"] == "fail"
    assert "PostGIS" in database_check["summary"]


def _status_for(result: dict[str, object], key: str) -> object:
    return _check_for(result, key)["status"]


def _check_for(result: dict[str, object], key: str) -> dict[str, str]:
    checks = result["checks"]
    assert isinstance(checks, list)
    for check in checks:
        assert isinstance(check, dict)
        if check["key"] == key:
            return check
    raise AssertionError(f"Missing check {key!r}")
