"""C05 policy/import regressions; actual lock races live in the PostGIS scenario."""

import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.phase3_store import _read_collection, _write_collection, reset_phase3_state
from app.processed_store import write_processed_list

TOKEN = "synthetic-c05-unit-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    for key, value in {
        "DATA_MODE": "live",
        "PHASE3_STORE_BACKEND": "artifact",
        "PROCESSED_STORE_BACKEND": "artifact",
        "INGESTION_DATA_DIR": str(tmp_path),
        "REVIEWER_API_TOKEN": TOKEN,
        "ARTIFACT_DURABILITY_REQUIRED": "false",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    reset_phase3_state(force_memory=True)
    write_processed_list("staged_development_records", [])
    write_processed_list("development_records", [])
    with TestClient(app, headers=HEADERS) as client:
        yield client
    reset_phase3_state()
    get_settings.cache_clear()


def submission(api: TestClient) -> dict[str, Any]:
    receipt = api.post(
        "/api/public-submissions",
        json={
            "title": "C05 unlocated tip",
            "notes": "Private source tip",
            "submitter_contact": "private@example.test",
            "source_url": "https://example.test/c05",
            "geometry": None,
        },
    )
    assert receipt.status_code == 200, receipt.text
    return api.get("/api/reviewer/staged-records").json()[-1]


def test_known_processed_id_is_read_only_and_unknown_remains_404(api: TestClient) -> None:
    from app.ingestion.normalize import normalize_new_subdivision

    row, _public, _errors = normalize_new_subdivision(
        {
            "type": "Feature",
            "properties": {"SubdID": 42, "Subdivision": "C05 audit"},
            "geometry": {"type": "Point", "coordinates": [-86.6, 34.7]},
        },
        "2026-10-15T00:00:00Z",
    )
    write_processed_list("staged_development_records", [row])
    staged = api.get(f"/api/reviewer/staged-records/{row['id']}").json()
    assert staged["origin"] == "processed" and staged["allowed_actions"] == []
    assert "ArcGIS" in staged["actionability_reason"]
    for action in ("approve", "reject", "needs-info"):
        response = api.post(f"/api/reviewer/staged-records/{row['id']}/{action}", json={})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "review_not_actionable"
        assert (
            api.post(f"/api/reviewer/staged-records/unknown/{action}", json={}).status_code == 404
        )


def test_submission_revision_history_terminal_policy_and_alias(api: TestClient) -> None:
    row = submission(api)
    assert row["revision"] == 1 and row["allowed_actions"] == ["needs_info", "reject"]
    url = f"/api/reviewer/staged-records/{row['id']}"
    assert api.post(f"{url}/reject", json={"notes": "Missing token"}).status_code == 409
    first = api.post(
        f"{url}/needs-info",
        json={
            "expected_revision": 1,
            "notes": "Retain this reason",
        },
    )
    assert first.status_code == 200, first.text
    stale = api.post(f"{url}/reject", json={"expected_revision": 1, "notes": "stale"})
    assert stale.status_code == 409
    alias = row["source_payload"]["submission_id"]
    assert (
        api.post(
            f"/api/reviewer/submissions/{alias}/reject",
            json={
                "expected_revision": 1,
                "notes": "alias stale",
            },
        ).status_code
        == 409
    )
    final = api.post(f"{url}/reject", json={"expected_revision": 2}).json()
    assert final["review_notes"] == "Retain this reason"
    assert len(final["review_history"]) == 2 and final["allowed_actions"] == []
    assert api.post(f"{url}/needs-info", json={"expected_revision": 3}).status_code == 409
    assert api.get(url).json() == final


def test_export_roundtrip_restore_suffix_and_conflicting_import(api: TestClient) -> None:
    row = submission(api)
    original = copy.deepcopy(_read_collection("submission_staged_records"))
    url = f"/api/reviewer/staged-records/{row['id']}"
    api.post(f"{url}/needs-info", json={"expected_revision": 1, "notes": "First private note"})
    api.post(f"{url}/reject", json={"expected_revision": 2, "notes": "Final private note"})
    exported = api.get("/api/reviewer/decisions/export").json()[0]
    final = api.get(url).json()
    unchanged = api.post("/api/reviewer/decisions/import", json={"decisions": [exported]})
    assert unchanged.json() == {"applied": 0, "missing": [], "conflicts": []}
    forged = copy.deepcopy(exported)
    forged["review_history"][0]["notes"] = "Overwrite history"
    assert api.post("/api/reviewer/decisions/import", json={"decisions": [forged]}).json()[
        "conflicts"
    ] == [row["id"]]
    assert api.get(url).json() == final
    # A copied older state can restore an exact legal suffix with its own current token.
    _write_collection("submission_staged_records", original)
    _write_collection("review_decision_events", [])
    exported["expected_revision"] = 1
    restored = api.post("/api/reviewer/decisions/import", json={"decisions": [exported]})
    assert restored.json() == {"applied": 1, "missing": [], "conflicts": []}, restored.text
    assert api.get(url).json() == final
    assert api.post("/api/reviewer/decisions/import", json={"decisions": [exported]}).json()[
        "conflicts"
    ] == [row["id"]]


def test_auth_import_validation_and_deferred_retraction(api: TestClient) -> None:
    row = submission(api)
    for path in ("/api/reviewer/staged-records", "/api/reviewer/decisions/export"):
        assert api.get(path, headers={"Authorization": ""}).status_code == 401
    url = f"/api/reviewer/staged-records/{row['id']}"
    assert api.post(f"{url}/reject", json={}, headers={"Authorization": ""}).status_code == 401
    assert (
        api.post(
            "/api/reviewer/decisions/import", json={"decisions": []}, headers={"Authorization": ""}
        ).status_code
        == 401
    )
    assert (
        api.post(f"{url}/retract", json={"reason": " ", "expected_revision": 1}).status_code == 422
    )
    response = api.post(
        f"{url}/retract", json={"reason": "Explicit reason", "expected_revision": 1}
    )
    assert response.status_code == 409 and "C06" in response.json()["detail"]["message"]
    assert (
        api.post(
            "/api/reviewer/decisions/import",
            json={
                "decisions": [
                    {
                        "staged_id": row["id"],
                        "review_status": "rejected",
                        "review_history": [{"id": "bad"}],
                    }
                ]
            },
        ).status_code
        == 422
    )
    assert "private@example.test" not in api.get("/api/development-records").text


def test_legacy_notes_are_retained_as_an_honest_baseline(api: TestClient) -> None:
    row = submission(api)
    stored = _read_collection("submission_staged_records")
    stored[0].pop("state_revision")
    stored[0].update(
        review_status="needs_info", review_notes="Legacy note without an actor or time"
    )
    _write_collection("submission_staged_records", stored)
    url = f"/api/reviewer/staged-records/{row['id']}"
    baseline = api.get(url).json()["review_history"][0]
    assert baseline["baseline"] and baseline["state_revision"] == 0
    assert baseline["actor"] == "unknown_legacy" and baseline["decided_at"] is None
    response = api.post(f"{url}/reject", json={"expected_revision": 0, "notes": "New reason"})
    assert response.status_code == 200, response.text
    assert response.json()["review_history"][0] == baseline
    assert len(response.json()["review_history"]) == 2
    snapshot = api.get("/api/reviewer/decisions/export").json()[0]
    assert api.post("/api/reviewer/decisions/import", json={"decisions": [snapshot]}).json() == {
        "applied": 0,
        "missing": [],
        "conflicts": [],
    }


def test_review_dependency_error_is_safe_503(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    from sqlalchemy.exc import SQLAlchemyError

    row = submission(api)

    @contextmanager
    def unavailable() -> Any:
        raise SQLAlchemyError("private database connection details")
        yield  # pragma: no cover

    monkeypatch.setattr("app.ingestion.agenda_store._agenda_mutation", unavailable)
    response = api.post(
        f"/api/reviewer/staged-records/{row['id']}/reject",
        json={
            "expected_revision": 1,
            "notes": "No write on failure",
        },
    )
    assert response.status_code == 503 and response.json()["detail"]["code"] == "data_unavailable"
    assert "private database connection" not in response.text


def test_demo_imported_approval_publishes_before_becoming_terminal(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.seed_store import demo_seed_development_records, get_staged_record, reset_seed_state

    monkeypatch.setenv("DATA_MODE", "demo")
    get_settings.cache_clear()
    reset_seed_state()
    staged_id = "stage-bradford-crossing-layout"
    staged = get_staged_record(staged_id)
    assert staged is not None
    public_id = staged["publish_record"]["public_id"]
    assert not any(row["public_id"] == public_id for row in demo_seed_development_records())
    current = api.get(f"/api/reviewer/staged-records/{staged_id}").json()
    response = api.post(
        "/api/reviewer/decisions/import",
        json={"decisions": [{
            "staged_id": staged_id,
            "review_status": "approved",
            "notes": "Imported demo approval",
            "expected_revision": current["revision"],
        }]},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"applied": 1, "missing": [], "conflicts": []}
    assert api.get(f"/api/development-records/{public_id}").status_code == 200
    assert sum(row["public_id"] == public_id for row in demo_seed_development_records()) == 1
    reviewed = api.get(f"/api/reviewer/staged-records/{staged_id}").json()
    assert reviewed["review_status"] == "approved"
    assert reviewed["revision"] == current["revision"] + 1
    assert reviewed["review_notes"] == "Imported demo approval"
    assert len(reviewed["review_history"]) == len(current["review_history"]) + 1
    repeated = api.post(
        f"/api/reviewer/staged-records/{staged_id}/approve",
        json={"expected_revision": reviewed["revision"]},
    )
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["code"] == "review_not_actionable"
    assert sum(row["public_id"] == public_id for row in demo_seed_development_records()) == 1
