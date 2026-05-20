from fastapi.testclient import TestClient

from app.main import app
from app.seed_store import reset_seed_state

client = TestClient(app)


def setup_function() -> None:
    reset_seed_state()


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


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

    staged_response = client.get("/api/reviewer/staged-records")
    assert staged_response.status_code == 200
    assert any(record["id"] == submission["staged_record_id"] for record in staged_response.json())

    approve_response = client.post(
        f"/api/reviewer/staged-records/{submission['staged_record_id']}/approve",
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

    alerts_response = client.get("/api/alerts")
    assert alerts_response.status_code == 200
    alerts = alerts_response.json()
    assert any(alert["watch_area_id"] == watch_area["id"] for alert in alerts)


def test_record_versions_and_change_log_are_available() -> None:
    versions_response = client.get("/api/development-records/hsv-westmoore-landing-ph1/versions")

    assert versions_response.status_code == 200
    assert versions_response.json()[0]["version_number"] == 1

    change_log_response = client.get("/api/change-log")
    assert change_log_response.status_code == 200
    assert change_log_response.json()
