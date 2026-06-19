from fastapi.testclient import TestClient

from app.alert_delivery import send_queued_email_alerts
from app.config import Settings, get_settings
from app.main import app
from app.phase3_store import list_alerts, list_watch_areas
from app.seed_store import reset_seed_state

client = TestClient(app)


def setup_function() -> None:
    reset_seed_state()


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_render_postgres_url_uses_psycopg_driver() -> None:
    settings = Settings(database_url="postgresql://user:pass@host:5432/db")

    assert settings.sqlalchemy_database_url == "postgresql+psycopg://user:pass@host:5432/db"


def test_lists_seed_development_records() -> None:
    response = client.get("/api/development-records")

    assert response.status_code == 200
    records = response.json()["records"]
    assert len(records) == 4
    assert records[0]["source_url"].startswith("https://")
    assert records[0]["geometry_source"]


def test_filters_records_by_status() -> None:
    response = client.get("/api/development-records", params={"status": "layout"})

    assert response.status_code == 200
    records = response.json()["records"]
    assert [record["status"] for record in records] == ["layout"]


def test_geojson_endpoint_returns_features() -> None:
    response = client.get("/api/map/development-records.geojson")

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 4
    assert body["features"][0]["geometry"]["type"] in {"Point", "Polygon"}


def test_record_detail_includes_provenance() -> None:
    response = client.get("/api/development-records/hsv-westmoore-landing-ph1")

    assert response.status_code == 200
    body = response.json()
    assert body["source_agency"] == "City of Huntsville GIS"
    assert body["confidence_level"] == "high"
    assert body["review_status"] == "published"


def test_reviewer_can_approve_staged_seed_record() -> None:
    approve_response = client.post(
        "/api/reviewer/staged-records/stage-bradford-crossing-layout/approve",
        json={"notes": "Geometry confirmed for seed workflow."},
    )

    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["public_id"] == "hsv-bradford-crossing-layout"
    assert approved["review_status"] == "published"

    detail_response = client.get("/api/development-records/hsv-bradford-crossing-layout")
    assert detail_response.status_code == 200


def test_source_health_endpoint_has_default_state() -> None:
    response = client.get("/api/source-health")

    assert response.status_code == 200
    assert "status" in response.json()


def test_public_submission_creates_reviewer_gated_staged_record() -> None:
    submission_response = client.post(
        "/api/public-submissions",
        json={
            "title": "Community Noticed Clearing",
            "source_url": "https://example.test/source",
            "notes": "Resident submitted a source link and rough boundary for reviewer validation.",
            "submitter_contact": "neighbor@example.test",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-86.62, 34.70],
                        [-86.61, 34.70],
                        [-86.61, 34.71],
                        [-86.62, 34.71],
                        [-86.62, 34.70],
                    ]
                ],
            },
        },
    )

    assert submission_response.status_code == 200
    submission = submission_response.json()
    assert submission["status"] == "pending"
    assert "submitter_contact_hash" not in submission

    staged_response = client.get("/api/reviewer/staged-records")
    assert staged_response.status_code == 200
    staged_records = staged_response.json()
    staged = next(
        record
        for record in staged_records
        if record["source_payload"].get("submission_id") == submission["id"]
    )

    approve_response = client.post(
        f"/api/reviewer/staged-records/{staged['id']}/approve",
        json={"notes": "Source reviewed."},
    )

    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["review_status"] == "published"
    assert approved["development_type"] == "public_submission"


def test_watch_area_queues_matching_email_alerts() -> None:
    response = client.post(
        "/api/watch-areas",
        json={
            "name": "Southwest Huntsville",
            "email": "watcher@example.test",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-87.0, 34.5],
                        [-86.0, 34.5],
                        [-86.0, 35.0],
                        [-87.0, 35.0],
                        [-87.0, 34.5],
                    ]
                ],
            },
            "filters": {
                "statuses": ["layout"],
                "development_types": ["subdivision"],
            },
        },
    )

    assert response.status_code == 200
    watch_area = response.json()
    assert watch_area["alert_count"] >= 1
    assert "email_hash" not in watch_area
    assert "email_address" not in watch_area
    assert "unsubscribe_token" not in watch_area
    assert "geometry" not in watch_area

    alerts_response = client.get("/api/reviewer/alerts")
    assert alerts_response.status_code == 200
    alerts = alerts_response.json()
    assert any(alert["watch_area_id"] == watch_area["id"] for alert in alerts)

    stored_watch_area = list_watch_areas()[0]
    assert stored_watch_area["email_address"] == "watcher@example.test"
    assert stored_watch_area["unsubscribe_token"]

    unsubscribe_response = client.get(
        f"/api/watch-areas/unsubscribe/{stored_watch_area['unsubscribe_token']}"
    )
    assert unsubscribe_response.status_code == 200
    assert unsubscribe_response.json()["email_hint"] == "wa***@example.test"
    assert list_watch_areas()[0]["unsubscribed_at"]


def test_send_queued_email_alerts_marks_alert_sent(monkeypatch) -> None:
    sent_messages = []

    class FakeSmtp:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            assert host == "smtp.example.test"
            assert port == 2525
            assert timeout == 20

        def __enter__(self) -> "FakeSmtp":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def starttls(self) -> None:
            return None

        def send_message(self, message: object) -> None:
            sent_messages.append(message)

    client.post(
        "/api/watch-areas",
        json={
            "name": "Southwest Huntsville",
            "email": "watcher@example.test",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-87.0, 34.5],
                        [-86.0, 34.5],
                        [-86.0, 35.0],
                        [-87.0, 35.0],
                        [-87.0, 34.5],
                    ]
                ],
            },
            "filters": {
                "statuses": ["layout"],
                "development_types": ["subdivision"],
            },
        },
    )

    monkeypatch.setenv("ALERT_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("ALERT_DELIVERY_RATE_LIMIT", "1")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "alerts@example.test")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://tracker.example.test")
    monkeypatch.setattr("app.alert_delivery.smtplib.SMTP", FakeSmtp)
    get_settings.cache_clear()
    try:
        result = send_queued_email_alerts()
    finally:
        get_settings.cache_clear()

    assert result["configured"] is True
    assert result["attempted"] == 1
    assert result["sent"] == 1
    assert sent_messages
    assert list_alerts()[0]["status"] == "sent"
    assert list_alerts()[0]["sent_at"]


def test_record_versions_and_change_log_are_available() -> None:
    versions_response = client.get("/api/development-records/hsv-westmoore-landing-ph1/versions")

    assert versions_response.status_code == 200
    assert versions_response.json()[0]["version_number"] == 1

    change_log_response = client.get("/api/change-log")
    assert change_log_response.status_code == 200
    assert change_log_response.json()


def test_reviewer_phase3_store_status_reports_memory_backend() -> None:
    response = client.get("/api/reviewer/phase3-store")

    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "memory"
    assert body["database_first"] is False
    assert any(collection["name"] == "public_submissions" for collection in body["collections"])


def test_reviewer_api_requires_bearer_token_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("REVIEWER_API_TOKEN", "test-reviewer-token")
    get_settings.cache_clear()
    try:
        blocked_response = client.get("/api/reviewer/staged-records")
        assert blocked_response.status_code == 401

        authorized_response = client.get(
            "/api/reviewer/staged-records",
            headers={"Authorization": "Bearer test-reviewer-token"},
        )
        assert authorized_response.status_code == 200
    finally:
        monkeypatch.delenv("REVIEWER_API_TOKEN", raising=False)
        get_settings.cache_clear()
