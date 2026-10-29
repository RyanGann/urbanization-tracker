"""C05 over real HTTP/PostGIS: audit ID, forced race, restore, restart and privacy."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from time import monotonic, sleep

import httpx
from sqlalchemy import text

from app.db import SessionLocal
from app.ingestion.normalize import normalize_new_subdivision
from app.schemas import DevelopmentRecord
from app.transactional_store import CollectionUnitOfWork

FEATURE = {
    "type": "Feature",
    "properties": {"SubdID": 905, "Subdivision": "C05 ArcGIS audit", "Status": "Layout"},
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [
                [-86.6, 34.7],
                [-86.59, 34.7],
                [-86.59, 34.71],
                [-86.6, 34.71],
                [-86.6, 34.7],
            ]
        ],
    },
}
CONTACT = "synthetic-private-c05@example.test"


def get(api: httpx.Client, staged_id: str) -> dict:
    response = api.get(f"/api/reviewer/staged-records/{staged_id}")
    assert response.status_code == 200, response.text
    return response.json()


def create(api: httpx.Client, title: str, located: bool = False) -> dict:
    response = api.post(
        "/api/public-submissions",
        json={
            "title": title,
            "notes": "Synthetic private source tip",
            "submitter_contact": CONTACT,
            "source_url": "https://example.test/c05",
            "geometry": FEATURE["geometry"] if located else None,
        },
    )
    assert response.status_code == 200, response.text
    assert CONTACT not in response.text and "hash" not in response.text
    rows = api.get("/api/reviewer/staged-records").json()
    return next(row for row in rows if row["title"] == title)


def run(api_url: str, token: str, result: Path, mode: str) -> None:
    with httpx.Client(
        base_url=api_url, headers={"Authorization": f"Bearer {token}"}, timeout=15
    ) as api:
        if mode == "verify":
            proof = json.loads(result.read_text())
            for staged_id, expected in proof["persisted"].items():
                assert get(api, staged_id) == expected
            for public_id, expected in proof["public_snapshots"].items():
                assert api.get(f"/api/development-records/{public_id}").json() == expected
            proof["restart_durable"] = True
            result.write_text(json.dumps(proof, indent=2) + "\n")
            return

        staged, published, errors = normalize_new_subdivision(FEATURE, "2026-10-15T00:00:00Z")
        assert not errors, errors
        # The real normalizer's actual staged ID, not a guessed public-record ID.
        with SessionLocal.begin() as session:
            with CollectionUnitOfWork(session).canonical_mutation() as uow:
                uow.upsert_processed("staged_development_records", staged["id"], staged)
                uow.upsert_processed("development_records", published["public_id"], published)
        audit = get(api, staged["id"])
        assert audit["origin"] == "processed" and audit["allowed_actions"] == []
        for action in ("approve", "reject", "needs-info"):
            response = api.post(f"/api/reviewer/staged-records/{staged['id']}/{action}", json={})
            assert response.status_code == 409, response.text
            assert response.json()["detail"]["code"] == "review_not_actionable"
        assert api.post("/api/reviewer/staged-records/unknown/reject", json={}).status_code == 404

        row = create(api, "C05 forced reviewer race")
        path = f"/api/reviewer/staged-records/{row['id']}"
        assert api.post(f"{path}/reject", json={"notes": "No token"}).status_code == 409
        barrier = Barrier(3)

        def reviewer(action: str) -> httpx.Response:
            with httpx.Client(base_url=api_url, headers=api.headers, timeout=15) as other:
                barrier.wait(timeout=5)
                return other.post(
                    f"{path}/{action}",
                    json={
                        "expected_revision": 1,
                        "notes": f"Private race {action}",
                    },
                )

        # Hold the documented lock until both independent HTTP transactions queue.
        # The SQL barrier proves overlap instead of relying on sleeps alone.
        with ThreadPoolExecutor(max_workers=2) as pool:
            with SessionLocal.begin() as session:
                CollectionUnitOfWork(session).acquire_canonical_mutation_lock()
                one = pool.submit(reviewer, "reject")
                two = pool.submit(reviewer, "needs-info")
                barrier.wait(timeout=5)
                deadline = monotonic() + 1.2
                while True:
                    waiting = session.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname=current_database() "
                            "AND wait_event_type='Lock' AND wait_event='advisory'"
                        )
                    )
                    if waiting == 2:
                        break
                    assert monotonic() < deadline, "both reviewer transactions did not reach lock"
                    session.execute(text("SELECT pg_stat_clear_snapshot()"))
                    sleep(0.01)
            responses = [one.result(), two.result()]
        assert sorted(r.status_code for r in responses) == [200, 409]
        conflict = next(r for r in responses if r.status_code == 409)
        assert conflict.json()["detail"]["code"] == "review_revision_conflict"
        final = get(api, row["id"])
        assert final["revision"] == 2 and len(final["review_history"]) == 1
        assert final["review_history"][0]["notes"] == final["review_notes"]
        with httpx.Client(base_url=api_url, headers=api.headers) as second_reader:
            assert get(second_reader, row["id"]) == final
        alias = row["source_payload"]["submission_id"]
        assert (
            api.post(
                f"/api/reviewer/submissions/{alias}/reject",
                json={
                    "expected_revision": 1,
                    "notes": "Alias stale",
                },
            ).status_code
            == 409
        )

        # A separate two-event candidate tests exact backup continuation into a copied older state.
        restore = create(api, "C05 history restore")
        restore_path = f"/api/reviewer/staged-records/{restore['id']}"
        with SessionLocal() as session:
            original = CollectionUnitOfWork(session).get_phase3(
                "submission_staged_records", restore["id"]
            )
        for action, rev, notes in (
            ("needs-info", 1, "First durable private note"),
            ("reject", 2, "Final durable private note"),
        ):
            response = api.post(
                f"{restore_path}/{action}",
                json={
                    "expected_revision": rev,
                    "notes": notes,
                },
            )
            assert response.status_code == 200, response.text
        expected_restore = get(api, restore["id"])
        exported = api.get("/api/reviewer/decisions/export").json()
        backup = next(d for d in exported if d["staged_id"] == restore["id"])
        assert (
            api.post("/api/reviewer/decisions/import", json={"decisions": [backup]}).json()[
                "applied"
            ]
            == 0
        )
        forged = copy.deepcopy(backup)
        forged["review_history"][0]["notes"] = "Overwrite attempted"
        assert api.post("/api/reviewer/decisions/import", json={"decisions": [forged]}).json()[
            "conflicts"
        ] == [restore["id"]]
        with SessionLocal.begin() as session:
            with CollectionUnitOfWork(session).canonical_mutation() as uow:
                assert original is not None
                uow.upsert_phase3("submission_staged_records", restore["id"], original)
                for event in backup["review_history"]:
                    uow.delete_phase3("review_decision_events", event["id"])
        backup["expected_revision"] = 1
        imported = api.post("/api/reviewer/decisions/import", json={"decisions": [backup]})
        assert imported.json() == {"applied": 1, "missing": [], "conflicts": []}, imported.text
        assert get(api, restore["id"]) == expected_restore
        assert api.post("/api/reviewer/decisions/import", json={"decisions": [backup]}).json()[
            "conflicts"
        ] == [restore["id"]]

        # Rejecting changed manual content must retain the already published snapshot/version.
        with SessionLocal.begin() as session:
            with CollectionUnitOfWork(session).canonical_mutation() as uow:
                old = copy.deepcopy(published)
                old.update(public_id="c05-old-public", title="C05 older published snapshot")
                old = DevelopmentRecord.model_validate(old).model_dump(mode="json")
                candidate = copy.deepcopy(staged)
                candidate.update(
                    id="stage-c05-agenda",
                    title="C05 changed agenda revision",
                    review_status="pending",
                    state_revision=2,
                    content_revision=2,
                    publish_record={**old, "title": "Changed content"},
                )
                uow.upsert_phase3("development_records", old["public_id"], old)
                uow.upsert_phase3("agenda_staged_records", candidate["id"], candidate)
                uow.upsert_phase3(
                    "record_versions",
                    "c05-old-version",
                    {
                        "id": "c05-old-version",
                        "public_id": old["public_id"],
                        "version_number": 1,
                        "snapshot": old,
                        "changed_at": "2026-10-14T00:00:00Z",
                        "changed_by": "reviewer",
                        "change_type": "published",
                    },
                )
        agenda_path = "/api/reviewer/staged-records/stage-c05-agenda"
        agenda = get(api, "stage-c05-agenda")
        assert (
            "approve" not in agenda["allowed_actions"] and "C06" in agenda["actionability_reason"]
        )
        blocked = api.post(f"{agenda_path}/approve", json={"expected_revision": 2})
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "agenda_publication_update_pending"
        rejected = api.post(
            f"{agenda_path}/reject",
            json={
                "expected_revision": 2,
                "notes": "New revision rejected; keep original public snapshot",
            },
        )
        assert rejected.status_code == 200, rejected.text
        for action in ("approve", "needs-info", "reject"):
            assert (
                api.post(f"{agenda_path}/{action}", json={"expected_revision": 3}).status_code
                == 409
            )
        assert api.get(f"/api/development-records/{old['public_id']}").json() == old
        assert (
            api.get(f"/api/development-records/{old['public_id']}/versions").json()[0]["snapshot"]
            == old
        )

        approved_row = create(api, "C05 approved submission", located=True)
        approved = api.post(
            f"/api/reviewer/staged-records/{approved_row['id']}/approve",
            json={
                "expected_revision": 1,
                "notes": "Private approval note",
            },
        )
        assert approved.status_code == 200, approved.text
        approved_public = approved.json()
        assert "Private approval note" not in approved.text and CONTACT not in approved.text
        assert get(api, approved_row["id"])["allowed_actions"] == []

        # Dedicated browser fixture is left pending for the no-interception live workflow.
        create(api, "C05 browser conflict")
        with httpx.Client(base_url=api_url) as public:
            for method, endpoint, body in (
                ("GET", "/api/reviewer/staged-records", None),
                ("GET", "/api/reviewer/decisions/export", None),
                ("POST", "/api/reviewer/decisions/import", {"decisions": []}),
                ("POST", f"{path}/reject", {"expected_revision": 2}),
            ):
                assert public.request(method, endpoint, json=body).status_code == 401
            for endpoint in (
                "/api/development-records",
                "/api/change-log",
                f"/api/development-records/{old['public_id']}/versions",
            ):
                body = public.get(endpoint).text
                assert CONTACT not in body and "Private race" not in body
                assert "durable private note" not in body and "review_actor" not in body
        persisted = {
            r["id"]: get(api, r["id"]) for r in (row, restore, candidate, staged, approved_row)
        }
        proof = {
            "fixture_sha256": hashlib.sha256(
                json.dumps(FEATURE, sort_keys=True).encode()
            ).hexdigest(),
            "processed_staged_id": staged["id"],
            "two_queued_http_transactions": True,
            "race_statuses": sorted(r.status_code for r in responses),
            "history_roundtrip_and_restore": True,
            "older_public_snapshot_retained": True,
            "auth_and_public_privacy": True,
            "submission_approval": True,
            "public_snapshots": {
                old["public_id"]: old,
                approved_public["public_id"]: approved_public,
            },
            "persisted": persisted,
        }
        result.write_text(json.dumps(proof, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--reviewer-token", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--mode", choices=("create", "verify"), required=True)
    args = parser.parse_args()
    run(args.api_url, args.reviewer_token, args.result, args.mode)
