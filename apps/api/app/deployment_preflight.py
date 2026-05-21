from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from sqlalchemy import create_engine, text

from app.config import Settings, get_settings

PreflightStatus = Literal["pass", "warn", "fail", "skip"]


@dataclass(frozen=True)
class PreflightCheck:
    key: str
    status: PreflightStatus
    summary: str
    detail: str | None = None

    def as_dict(self) -> dict[str, str]:
        payload = {
            "key": self.key,
            "status": self.status,
            "summary": self.summary,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass(frozen=True)
class DatabaseProbeResult:
    reachable: bool
    postgis_enabled: bool
    database: str | None = None
    error: str | None = None


DatabaseProbe = Callable[[Settings], DatabaseProbeResult]


def run_deployment_preflight(
    *,
    settings: Settings | None = None,
    check_database: bool = True,
    database_probe: DatabaseProbe | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    checks = [
        _check_reviewer_token(active_settings),
        _check_phase3_store(active_settings),
        _check_cors_origins(active_settings),
        _check_public_base_url(active_settings),
        _check_alert_delivery(active_settings),
        _check_database_url(active_settings),
        _check_database(
            active_settings,
            check_database=check_database,
            database_probe=database_probe,
        ),
    ]
    status = _aggregate_status(checks)
    summary = {
        "passed": sum(1 for check in checks if check.status == "pass"),
        "warnings": sum(1 for check in checks if check.status == "warn"),
        "failed": sum(1 for check in checks if check.status == "fail"),
        "skipped": sum(1 for check in checks if check.status == "skip"),
    }
    return {
        "status": status,
        "summary": summary,
        "checks": [check.as_dict() for check in checks],
    }


def _check_reviewer_token(settings: Settings) -> PreflightCheck:
    token = (settings.reviewer_api_token or "").strip()
    if not token:
        return PreflightCheck(
            key="reviewer_access",
            status="fail",
            summary="REVIEWER_API_TOKEN is not set.",
            detail=(
                "Production reviewer routes must require a bearer token even when edge access "
                "is also used."
            ),
        )
    if len(token) < 24:
        return PreflightCheck(
            key="reviewer_access",
            status="warn",
            summary="REVIEWER_API_TOKEN is set but short.",
            detail="Use a generated secret with at least 24 characters.",
        )
    return PreflightCheck(
        key="reviewer_access",
        status="pass",
        summary="Reviewer bearer token is configured.",
    )


def _check_phase3_store(settings: Settings) -> PreflightCheck:
    backend = settings.phase3_store_backend.lower()
    if backend != "postgres":
        return PreflightCheck(
            key="phase3_store",
            status="fail",
            summary="PHASE3_STORE_BACKEND must be postgres for production.",
            detail=f"Current backend is {settings.phase3_store_backend!r}.",
        )
    return PreflightCheck(
        key="phase3_store",
        status="pass",
        summary="Phase 3 operational collections use Postgres.",
    )


def _check_cors_origins(settings: Settings) -> PreflightCheck:
    origins = settings.cors_origin_list
    if not origins:
        return PreflightCheck(
            key="cors_origins",
            status="fail",
            summary="CORS_ORIGINS is empty.",
        )
    if "*" in origins:
        return PreflightCheck(
            key="cors_origins",
            status="fail",
            summary="CORS_ORIGINS must not allow every origin in production.",
        )
    local_origins = [origin for origin in origins if _is_local_url(origin)]
    insecure_origins = [origin for origin in origins if not _is_https_url(origin)]
    if local_origins or insecure_origins:
        detail = ", ".join(sorted(set(local_origins + insecure_origins)))
        return PreflightCheck(
            key="cors_origins",
            status="fail",
            summary="CORS_ORIGINS must contain deployed HTTPS origins only.",
            detail=detail,
        )
    return PreflightCheck(
        key="cors_origins",
        status="pass",
        summary=f"{len(origins)} deployed CORS origin(s) configured.",
    )


def _check_public_base_url(settings: Settings) -> PreflightCheck:
    public_base_url = settings.public_base_url.rstrip("/")
    if not _is_https_url(public_base_url) or _is_local_url(public_base_url):
        return PreflightCheck(
            key="public_base_url",
            status="fail",
            summary="PUBLIC_BASE_URL must be the deployed HTTPS web origin.",
            detail=f"Current value is {settings.public_base_url!r}.",
        )
    return PreflightCheck(
        key="public_base_url",
        status="pass",
        summary="Public base URL is a deployed HTTPS origin.",
    )


def _check_alert_delivery(settings: Settings) -> PreflightCheck:
    if settings.alert_delivery_rate_limit < 1:
        return PreflightCheck(
            key="alert_delivery",
            status="fail",
            summary="ALERT_DELIVERY_RATE_LIMIT must be at least 1.",
        )
    if not settings.alert_delivery_enabled:
        return PreflightCheck(
            key="alert_delivery",
            status="warn",
            summary="Alert delivery is disabled.",
            detail="Queued alerts will remain internal until ALERT_DELIVERY_ENABLED is true.",
        )
    missing = [
        name
        for name, value in (
            ("SMTP_HOST", settings.smtp_host),
            ("SMTP_FROM_EMAIL", settings.smtp_from_email),
        )
        if not value
    ]
    if missing:
        return PreflightCheck(
            key="alert_delivery",
            status="fail",
            summary="Alert delivery is enabled but SMTP settings are incomplete.",
            detail=", ".join(missing),
        )
    if "@" not in str(settings.smtp_from_email):
        return PreflightCheck(
            key="alert_delivery",
            status="fail",
            summary="SMTP_FROM_EMAIL must be an email address.",
            detail=f"Current value is {settings.smtp_from_email!r}.",
        )
    return PreflightCheck(
        key="alert_delivery",
        status="pass",
        summary="Alert delivery settings are complete.",
    )


def _check_database_url(settings: Settings) -> PreflightCheck:
    parsed = urlparse(settings.sqlalchemy_database_url)
    if parsed.scheme not in {"postgresql+psycopg", "postgresql"}:
        return PreflightCheck(
            key="database_url",
            status="fail",
            summary="DATABASE_URL must point to PostgreSQL/PostGIS.",
            detail=f"Current SQLAlchemy scheme is {parsed.scheme!r}.",
        )
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return PreflightCheck(
            key="database_url",
            status="warn",
            summary="DATABASE_URL points at localhost.",
            detail="This is expected for local dry runs but not for the hosted alpha.",
        )
    return PreflightCheck(
        key="database_url",
        status="pass",
        summary="Database URL uses PostgreSQL.",
    )


def _check_database(
    settings: Settings,
    *,
    check_database: bool,
    database_probe: DatabaseProbe | None,
) -> PreflightCheck:
    if not check_database:
        return PreflightCheck(
            key="database_probe",
            status="skip",
            summary="Database connectivity and PostGIS probe skipped.",
        )
    probe = database_probe or probe_database
    result = probe(settings)
    if not result.reachable:
        return PreflightCheck(
            key="database_probe",
            status="fail",
            summary="Database connection failed.",
            detail=result.error,
        )
    if not result.postgis_enabled:
        return PreflightCheck(
            key="database_probe",
            status="fail",
            summary="PostGIS extension is not enabled.",
            detail=f"Database: {result.database}" if result.database else None,
        )
    return PreflightCheck(
        key="database_probe",
        status="pass",
        summary="Database is reachable and PostGIS is enabled.",
        detail=f"Database: {result.database}" if result.database else None,
    )


def probe_database(settings: Settings) -> DatabaseProbeResult:
    engine = create_engine(settings.sqlalchemy_database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                      current_database() AS database_name,
                      EXISTS (
                        SELECT 1 FROM pg_extension WHERE extname = 'postgis'
                      ) AS postgis_enabled
                    """
                )
            ).mappings().one()
        return DatabaseProbeResult(
            reachable=True,
            postgis_enabled=bool(row["postgis_enabled"]),
            database=str(row["database_name"]),
        )
    except Exception as exc:  # pragma: no cover - provider and network failures vary.
        return DatabaseProbeResult(
            reachable=False,
            postgis_enabled=False,
            error=str(exc),
        )
    finally:
        engine.dispose()


def _aggregate_status(checks: list[PreflightCheck]) -> PreflightStatus:
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "pass"


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _is_local_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.hostname in {"localhost", "127.0.0.1", "::1"}
