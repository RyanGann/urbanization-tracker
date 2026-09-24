from __future__ import annotations

from typing import Any

import pytest

from app import deployment_preflight
from app.config import Settings
from app.deployment_preflight import DatabaseProbeResult, run_deployment_preflight


def production_settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql://tracker:secret@db.internal:5432/tracker",
        "cors_origins": "https://tracker.example.test",
        "reviewer_api_token": "reviewer-secret-token-with-length",
        "phase3_store_backend": "postgres",
        "processed_store_backend": "postgres",
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
    assert _status_for(result, "processed_store") == "fail"
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


def test_deployment_preflight_fails_when_processed_store_is_not_postgres() -> None:
    result = run_deployment_preflight(
        settings=production_settings(processed_store_backend="artifact"),
        check_database=False,
    )

    processed_store_check = _check_for(result, "processed_store")
    assert processed_store_check["status"] == "fail"
    assert "PROCESSED_STORE_BACKEND" in processed_store_check["summary"]


def test_hosted_ingestion_rejects_local_artifact_sink() -> None:
    result = run_deployment_preflight(
        settings=production_settings(
            hosted_ingestion_enabled=True,
            artifact_durability_required=True,
            artifact_sink="local",
        ),
        check_database=False,
    )

    assert _status_for(result, "artifact_storage") == "fail"


def test_hosted_ingestion_requires_complete_s3_configuration() -> None:
    settings = production_settings(
        hosted_ingestion_enabled=True,
        artifact_durability_required=True,
        artifact_sink="s3",
        artifact_s3_endpoint="https://objects.example.test",
        artifact_s3_bucket="private-artifacts",
        artifact_s3_access_key="synthetic-access",
        artifact_s3_secret_key="synthetic-secret",
    )
    configured = run_deployment_preflight(settings=settings, check_database=False)
    missing = run_deployment_preflight(
        settings=settings.model_copy(update={"artifact_s3_bucket": None}),
        check_database=False,
    )

    assert _status_for(configured, "artifact_storage") == "pass"
    assert _status_for(missing, "artifact_storage") == "fail"


@pytest.mark.parametrize(
    "invalid",
    [
        {"artifact_s3_endpoint": "http://objects.example.test"},
        {"artifact_s3_endpoint": "https://objects.example.test/private"},
        {"artifact_s3_endpoint": "https://objects.example.test?token=private"},
        {"artifact_s3_region": ""},
        {"artifact_s3_bucket": "b" * 64},
        {"artifact_s3_access_key": ""},
        {"artifact_s3_secret_key": ""},
    ],
)
def test_hosted_ingestion_preflight_rejects_unusable_s3_settings(
    invalid: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "hosted_ingestion_enabled": True,
        "artifact_durability_required": True,
        "artifact_sink": "s3",
        "artifact_s3_endpoint": "https://objects.example.test",
        "artifact_s3_bucket": "private-artifacts",
        "artifact_s3_region": "us-east-1",
        "artifact_s3_access_key": "synthetic-access",
        "artifact_s3_secret_key": "synthetic-secret",
    }
    values.update(invalid)
    result = run_deployment_preflight(
        settings=production_settings(**values), check_database=False
    )

    assert _status_for(result, "artifact_storage") == "fail"


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


def test_deployment_preflight_rejects_non_origin_cors_entries() -> None:
    result = run_deployment_preflight(
        settings=production_settings(
            cors_origins=(
                "https://tracker.example.test,"
                "https://tracker.example.test/,"
                "https://tracker.example.test/app,"
                "https://tracker.example.test?preview=1"
            )
        ),
        check_database=False,
    )

    cors_check = _check_for(result, "cors_origins")
    assert cors_check["status"] == "fail"
    assert "https://tracker.example.test/" in cors_check["detail"]
    assert "https://tracker.example.test/app" in cors_check["detail"]
    assert "https://tracker.example.test?preview=1" in cors_check["detail"]


def test_deployment_preflight_rejects_non_origin_public_base_url() -> None:
    result = run_deployment_preflight(
        settings=production_settings(public_base_url="https://tracker.example.test/app?preview=1"),
        check_database=False,
    )

    public_base_url_check = _check_for(result, "public_base_url")
    assert public_base_url_check["status"] == "fail"
    assert "https://tracker.example.test/app?preview=1" in public_base_url_check["detail"]


def test_probe_database_uses_bounded_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_create_engine(url: str, **kwargs: object) -> object:
        calls.append({"url": url, **kwargs})

        class FakeEngine:
            def connect(self) -> object:
                raise RuntimeError("stop before network")

            def dispose(self) -> None:
                pass

        return FakeEngine()

    monkeypatch.setattr(deployment_preflight, "create_engine", fake_create_engine)

    result = deployment_preflight.probe_database(production_settings())

    assert result.reachable is False
    assert calls == [
        {
            "url": production_settings().sqlalchemy_database_url,
            "pool_pre_ping": True,
            "connect_args": {
                "connect_timeout": deployment_preflight.DATABASE_PROBE_CONNECT_TIMEOUT_SECONDS,
                "options": (
                    "-c statement_timeout="
                    f"{deployment_preflight.DATABASE_PROBE_STATEMENT_TIMEOUT_MS}"
                ),
            },
        }
    ]


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


def test_deployment_preflight_fails_in_demo_mode() -> None:
    result = run_deployment_preflight(
        settings=production_settings(data_mode="demo"),
        check_database=False,
    )

    data_mode_check = _check_for(result, "data_mode")
    assert data_mode_check["status"] == "fail"
    assert "DATA_MODE" in data_mode_check["summary"]
