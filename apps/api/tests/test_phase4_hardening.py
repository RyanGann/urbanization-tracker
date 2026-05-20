from time import perf_counter

from fastapi.testclient import TestClient

from app.ingestion.geometry import centroid
from app.jurisdictions import active_sources, list_jurisdictions
from app.main import app
from app.phase3_store import build_duplicate_candidates
from app.schemas import DevelopmentRecord
from app.seed_store import development_records_geojson, reset_seed_state

client = TestClient(app)


def setup_function() -> None:
    reset_seed_state()


def test_jurisdiction_configs_include_second_pilot_source() -> None:
    jurisdictions = list_jurisdictions()

    assert {jurisdiction.id for jurisdiction in jurisdictions} >= {
        "huntsville-al",
        "madison-county-al-demo",
    }
    assert any(source.key == "madison_county_demo_planning_cases" for _, source in active_sources())


def test_connector_health_lists_configured_sources_even_before_runs() -> None:
    response = client.get("/api/connector-health")

    assert response.status_code == 200
    rows = response.json()
    keys = {row["key"] for row in rows}
    assert "huntsville_new_subdivisions" in keys
    assert "madison_county_demo_planning_cases" in keys
    demo = next(row for row in rows if row["key"] == "madison_county_demo_planning_cases")
    assert demo["status"] in {"not_run", "healthy", "degraded", "failing"}


def test_reviewer_decision_export_import_roundtrip() -> None:
    export_response = client.get("/api/reviewer/decisions/export")

    assert export_response.status_code == 200
    exported = export_response.json()
    assert any(decision["staged_id"] == "stage-bradford-crossing-layout" for decision in exported)

    import_response = client.post(
        "/api/reviewer/decisions/import",
        json={
            "decisions": [
                {
                    "staged_id": "stage-bradford-crossing-layout",
                    "review_status": "needs_info",
                    "notes": "Imported from reviewer handoff.",
                }
            ]
        },
    )

    assert import_response.status_code == 200
    assert import_response.json() == {"applied": 1, "missing": []}


def test_large_geojson_serialization_performance_smoke() -> None:
    records = [_synthetic_record(index) for index in range(2500)]

    started_at = perf_counter()
    collection = development_records_geojson(records)
    elapsed = perf_counter() - started_at

    assert len(collection["features"]) == 2500
    assert elapsed < 2.0


def test_duplicate_candidate_generation_performance_smoke() -> None:
    published = [_synthetic_record(index).model_dump() for index in range(500)]
    staged = [
        {
            "id": f"stage-synthetic-{index}",
            "title": f"Synthetic Growth Area {index}",
            "normalized_status": "layout",
        }
        for index in range(500)
    ]

    started_at = perf_counter()
    candidates = build_duplicate_candidates(staged, published)
    elapsed = perf_counter() - started_at

    assert candidates
    assert elapsed < 2.0


def _synthetic_record(index: int) -> DevelopmentRecord:
    lon = -86.8 + (index % 100) * 0.001
    lat = 34.6 + (index // 100) * 0.001
    geometry = {
        "type": "Point",
        "coordinates": [lon, lat],
    }
    return DevelopmentRecord(
        public_id=f"synthetic-growth-area-{index}",
        title=f"Synthetic Growth Area {index}",
        description="Synthetic performance-test record.",
        development_type="subdivision",
        status="layout",
        source_status="Layout",
        source_url="https://example.test/source",
        source_agency="Synthetic Test",
        date_discovered="2026-05-20",
        date_last_checked="2026-05-20",
        review_status="published",
        confidence_level="high",
        geometry_source="Synthetic test geometry",
        geometry_confidence="high",
        geometry=geometry,
        centroid=centroid(geometry),
        source_fields={},
    )
