"""C04 identity and decision-retention cases without external source refresh."""

from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any

import pytest

from app.ingestion.agenda import parse_agenda_items
from app.ingestion.agenda_inventory import build_inventory
from app.ingestion.agenda_store import (
    _digest,
    _merge_agenda_batch,
    _merge_candidate,
    _merge_document,
)


class MemoryUow:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    def get_phase3(self, collection: str, key: str) -> dict[str, Any] | None:
        value = self.rows[collection].get(key)
        return copy.deepcopy(value) if value is not None else None

    def list_phase3(self, collection: str) -> list[dict[str, Any]]:
        return copy.deepcopy(list(self.rows[collection].values()))

    def upsert_phase3(self, collection: str, key: str, value: dict[str, Any]) -> None:
        self.rows[collection][key] = copy.deepcopy(value)


def _document(sha: str, *, url: str = "https://example.test/agenda.pdf") -> dict[str, Any]:
    return {
        "id": f"agenda-{sha[:12]}",
        "title": "Planning agenda April 28, 2026",
        "url": url,
        "document_date": "2026-04-28",
        "fetched_at": "2026-04-29T00:00:00Z",
        "sha256": sha,
        "text_sha256": sha,
        "extraction_status": "extracted",
        "pdf_reference_id": None,
        "text_reference_id": None,
    }


def _records(document: dict[str, Any], *, status: str = "Layout") -> list[dict[str, Any]]:
    return parse_agenda_items(
        f"1. SAMPLE RIDGE\n{status} (24 lots) Developer: Builder\nLocated: West of Road",
        source_document=document,
        checked_at="2026-04-29T00:00:00Z",
    )


def test_same_revision_replay_retains_rejection_and_never_fabricates_location() -> None:
    uow = MemoryUow()
    document = _document("a" * 64)
    doc_id, revision_id = _merge_document(uow, document, "run-a")
    assert doc_id and revision_id
    parsed = _records(document)[0]
    assert parsed["geometry"] is None
    assert parsed["publish_record"]["centroid"] is None
    candidate_id = _merge_candidate(
        uow,
        parsed,
        document_id=doc_id,
        revision_id=revision_id,
        document_date=document["document_date"],
    )
    assert candidate_id
    rejected = uow.get_phase3("agenda_staged_records", candidate_id)
    assert rejected
    rejected["review_status"] = "rejected"
    rejected["review_notes"] = "Cannot verify location"
    rejected["state_revision"] = 2
    uow.upsert_phase3("agenda_staged_records", candidate_id, rejected)
    doc_again, rev_again = _merge_document(uow, document, "run-b")
    assert (doc_again, rev_again) == (doc_id, revision_id)
    assert (
        _merge_candidate(
            uow,
            parsed,
            document_id=doc_id,
            revision_id=revision_id,
            document_date=document["document_date"],
        )
        == candidate_id
    )
    after = uow.get_phase3("agenda_staged_records", candidate_id)
    assert after and after["review_status"] == "rejected"
    assert after["review_notes"] == "Cannot verify location"
    assert after["state_revision"] == 2
    assert len(uow.rows["agenda_candidate_revisions"]) == 1


def test_changed_unanchored_observation_waits_for_audited_mapping() -> None:
    uow = MemoryUow()
    old = _document("a" * 64)
    doc_id, old_revision = _merge_document(uow, old, "run-a")
    assert doc_id and old_revision
    original = _records(old)[0]
    candidate_id = _merge_candidate(
        uow,
        original,
        document_id=doc_id,
        revision_id=old_revision,
        document_date=old["document_date"],
    )
    assert candidate_id
    reviewed = uow.get_phase3("agenda_staged_records", candidate_id)
    assert reviewed
    reviewed["review_status"] = "approved"
    reviewed["review_notes"] = "Prior source was verified"
    uow.upsert_phase3("agenda_staged_records", candidate_id, reviewed)

    changed = _document("b" * 64)
    next_doc, next_revision = _merge_document(uow, changed, "run-b")
    assert next_doc == doc_id and next_revision != old_revision
    new_observation = _records(changed, status="Final")[0]
    assert (
        _merge_candidate(
            uow,
            new_observation,
            document_id=doc_id,
            revision_id=next_revision,
            document_date=changed["document_date"],
        )
        is None
    )
    # The initial revision also has an observation. Locate the new unresolved one.
    unresolved = next(
        item
        for item in uow.rows["agenda_observations"].values()
        if item["status"] == "identity_unresolved"
    )
    assert unresolved["candidate_id"] is None
    assert uow.get_phase3("agenda_staged_records", candidate_id)["review_status"] == "approved"
    assert len(uow.rows["agenda_candidate_revisions"]) == 1

    unresolved["candidate_id"] = candidate_id
    unresolved["status"] = "resolved"
    uow.upsert_phase3("agenda_observations", unresolved["id"], unresolved)
    assert (
        _merge_candidate(
            uow,
            new_observation,
            document_id=doc_id,
            revision_id=next_revision,
            document_date=changed["document_date"],
        )
        == candidate_id
    )
    current = uow.get_phase3("agenda_staged_records", candidate_id)
    assert current and current["review_status"] == "pending"
    assert current["content_revision"] == 2
    assert len(uow.rows["agenda_candidate_revisions"]) == 2
    assert (
        uow.rows["agenda_decision_events"][f"{candidate_id}:legacy-baseline"]["action"]
        == "approved"
    )


def test_same_legacy_title_id_cannot_link_across_document_revisions() -> None:
    uow = MemoryUow()
    document = _document("a" * 64)
    document_id, old_revision = _merge_document(uow, document, "old")
    assert document_id and old_revision
    record = _records(document)[0]
    candidate_id = _merge_candidate(
        uow,
        record,
        document_id=document_id,
        revision_id=old_revision,
        document_date=document["document_date"],
    )
    assert candidate_id
    newer = copy.deepcopy(record)
    newer["source_status"] = "Final"
    newer["normalized_status"] = "final"
    # A parser/extraction revision can retain the old title-derived legacy ID.
    # It is still a new unanchored observation, even if that ID resolves.
    assert (
        _merge_candidate(
            uow,
            newer,
            document_id=document_id,
            revision_id="new-extraction-revision",
            document_date=document["document_date"],
        )
        is None
    )
    assert uow.get_phase3("agenda_staged_records", candidate_id)["review_status"] == "pending"


def test_three_newer_documents_do_not_delete_older_document() -> None:
    uow = MemoryUow()
    first = _document("a" * 64)
    first_id, _ = _merge_document(uow, first, "first")
    for number, char in enumerate("bcd", start=1):
        newer = _document(char * 64, url=f"https://example.test/{number}/agenda.pdf")
        newer["document_date"] = f"2026-05-{number:02d}"
        _merge_document(uow, newer, f"run-{number}")
    assert first_id in uow.rows["source_documents"]
    assert len(uow.rows["source_documents"]) == 4


def test_changed_url_is_quarantined_until_explicit_alias_mapping() -> None:
    uow = MemoryUow()
    original = _document("a" * 64)
    old_id, _ = _merge_document(uow, original, "run-old")
    assert old_id
    moved = _document("b" * 64, url="https://example.test/moved/agenda.pdf")
    assert _merge_document(uow, moved, "run-moved") == (None, None)
    assert list(uow.rows["source_documents"]) == [old_id]
    unresolved = next(iter(uow.rows["agenda_unresolved_documents"].values()))
    assert unresolved["status"] == "identity_unresolved"
    alias_key = _digest(["huntsville_planning_agendas", moved["url"], moved["document_date"]])
    # The operator resolution command writes this alias with CAS and an audit
    # event; the next verified run may then follow it without guessing.
    uow.upsert_phase3(
        "agenda_document_aliases",
        alias_key,
        {
            "id": alias_key,
            "document_id": old_id,
            "url": moved["url"],
            "document_date": moved["document_date"],
        },
    )
    assert _merge_document(uow, moved, "run-retry")[0] == old_id


def test_changed_date_observations_with_same_pdf_remain_distinct() -> None:
    uow = MemoryUow()
    original = _document("a" * 64)
    assert _merge_document(uow, original, "run-old")[0]
    first_date = _document("b" * 64, url=original["url"])
    first_date["document_date"] = "2026-05-26"
    second_date = copy.deepcopy(first_date)
    second_date["document_date"] = "2026-06-23"
    assert _merge_document(uow, first_date, "run-one") == (None, None)
    assert _merge_document(uow, second_date, "run-two") == (None, None)
    assert len(uow.rows["agenda_unresolved_documents"]) == 2


def test_legacy_same_content_backfill_preserves_approval_and_notes() -> None:
    uow = MemoryUow()
    document = _document("a" * 64)
    parsed = _records(document)[0]
    parsed["review_status"] = "approved"
    parsed["review_notes"] = "Historical approved decision"
    uow.upsert_phase3("source_documents", document["id"], document)
    uow.upsert_phase3("agenda_staged_records", parsed["id"], parsed)
    doc_id, revision_id = _merge_document(uow, document, "run-backfill")
    assert doc_id and revision_id
    candidate_id = _merge_candidate(
        uow,
        _records(document)[0],
        document_id=doc_id,
        revision_id=revision_id,
        document_date=document["document_date"],
    )
    assert candidate_id == parsed["id"]
    after = uow.get_phase3("agenda_staged_records", candidate_id)
    assert after and after["review_status"] == "approved"
    assert after["review_notes"] == "Historical approved decision"
    assert after["state_revision"] == 1
    assert uow.rows["agenda_decision_events"][f"{candidate_id}:legacy-baseline"]["baseline"]


def test_inventory_identifies_legacy_gaps_without_deriving_identity() -> None:
    old_document = {"id": "legacy-doc", "url": "https://example.test/agenda.pdf"}
    new_document = {"id": "revisioned-doc"}
    result = build_inventory(
        documents=[old_document, new_document],
        candidates=[
            {"id": "reviewed", "title": "A", "review_status": "rejected"},
            {"id": "pending", "title": "A", "review_status": "pending"},
        ],
        aliases=[{"document_id": "revisioned-doc"}],
        document_revisions=[{"document_id": "revisioned-doc"}],
        candidate_revisions=[{"candidate_id": "pending"}],
        decision_events=[],
    )
    assert result["read_only"] is True
    assert result["missing_counts"] == {
        "document_alias": 1,
        "document_revision": 1,
        "candidate_revision": 1,
        "decision_baseline": 1,
    }
    assert result["samples"]["document_alias"] == ["legacy-doc"]
    assert result["samples"]["decision_baseline"] == ["reviewed"]


def test_historical_replay_preserves_latest_document_candidate_and_publication() -> None:
    uow = MemoryUow()
    old = _document("a" * 64)
    doc_id, old_revision = _merge_document(uow, old, "run-a")
    assert doc_id and old_revision
    candidate_id = _merge_candidate(
        uow,
        _records(old)[0],
        document_id=doc_id,
        revision_id=old_revision,
        document_date=old["document_date"],
    )
    assert candidate_id
    newer = _document("b" * 64)
    _, new_revision = _merge_document(uow, newer, "run-b")
    assert new_revision
    incoming = _records(newer, status="Final")[0]
    assert (
        _merge_candidate(
            uow,
            incoming,
            document_id=doc_id,
            revision_id=new_revision,
            document_date=newer["document_date"],
        )
        is None
    )
    occurrence = next(
        row
        for row in uow.rows["agenda_observations"].values()
        if row["status"] == "identity_unresolved"
    )
    occurrence["candidate_id"] = candidate_id
    occurrence["status"] = "resolved"
    uow.upsert_phase3("agenda_observations", occurrence["id"], occurrence)
    assert (
        _merge_candidate(
            uow,
            incoming,
            document_id=doc_id,
            revision_id=new_revision,
            document_date=newer["document_date"],
        )
        == candidate_id
    )
    current = uow.get_phase3("agenda_staged_records", candidate_id)
    assert current and current["content_revision"] == 2
    current.update(
        review_status="rejected",
        review_notes="Decision on latest revision",
        state_revision=3,
        review_actor="fixture",
        reviewed_at="2026-05-01",
    )
    uow.upsert_phase3("agenda_staged_records", candidate_id, current)
    public_id = current["publish_record"]["public_id"]
    uow.upsert_phase3(
        "development_records", public_id, {"public_id": public_id, "title": "old public"}
    )
    before = copy.deepcopy(uow.rows)
    _merge_agenda_batch(uow, [old], _records(old), {"status": "healthy"}, "run-a-replay")
    for collection in (
        "source_documents",
        "agenda_staged_records",
        "development_records",
        "agenda_candidate_revisions",
        "agenda_decision_events",
    ):
        assert uow.rows[collection] == before[collection]
    assert len(uow.rows["agenda_document_observations"]) == 3
    # The same protection applies to pre-marker checkpoints with revision evidence.
    for row in uow.rows["agenda_observations"].values():
        row.pop("applied_content_revision", None)
    _merge_agenda_batch(uow, [old], _records(old), {"status": "healthy"}, "legacy-replay")
    assert uow.rows["agenda_staged_records"] == before["agenda_staged_records"]


def test_limited_refresh_reports_all_retained_unresolved_identities() -> None:
    uow = MemoryUow()
    for name in ("agenda_unresolved_documents", "agenda_observations"):
        uow.upsert_phase3(
            name, "old-unresolved", {"id": "old-unresolved", "status": "identity_unresolved"}
        )
        uow.upsert_phase3(name, "resolved", {"id": "resolved", "status": "resolved"})
    newer = _document("c" * 64)
    health = _merge_agenda_batch(uow, [newer], [], {"status": "healthy"}, "limited")
    assert health["status"] == "degraded"
    assert health["identity_unresolved_count"] == 2
    assert health["validation_errors"] == ["agenda_identity_unresolved"]


def test_public_health_preserves_safe_identity_code_and_redacts_private_errors() -> None:
    from app.schemas import PublicSourceHealthRow

    health = PublicSourceHealthRow.model_validate(
        {
            "key": "huntsville_planning_agendas",
            "status": "degraded",
            "validation_errors": [
                "agenda_identity_unresolved",
                "private error: /objects/secret.pdf",
            ],
        }
    )
    assert health.validation_errors == ["agenda_identity_unresolved", "source_error"]


def test_artifact_decision_round_trip_and_failed_validation(
    tmp_path: Any, monkeypatch: Any
) -> None:
    from app.config import get_settings
    from app.ingestion.agenda_store import (
        AgendaRevisionConflict,
        list_unresolved_documents,
        list_unresolved_observations,
        merge_agenda_artifacts,
        resolve_agenda_document_alias,
        resolve_agenda_observation,
    )
    from app.phase3_store import (
        _read_collection,
        get_phase3_staged_record,
        reset_phase3_state,
        set_phase3_staged_review_status,
    )

    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PHASE3_STORE_BACKEND", "artifact")
    monkeypatch.setenv("DATA_MODE", "live")
    monkeypatch.setenv("ARTIFACT_DURABILITY_REQUIRED", "false")
    monkeypatch.setenv("HOSTED_INGESTION_ENABLED", "false")
    get_settings.cache_clear()
    reset_phase3_state(force_memory=False)
    try:
        old = _document("a" * 64)
        merge_agenda_artifacts(
            source_documents=[old],
            staged_records=_records(old),
            health={"status": "healthy"},
            run_id="a",
        )
        candidate = _read_collection("agenda_staged_records")[0]
        rejected = set_phase3_staged_review_status(
            candidate["id"], "rejected", notes="Retain private note", expected_revision=1
        )
        assert rejected and rejected["state_revision"] == 2
        reset_phase3_state(force_memory=False)
        merge_agenda_artifacts(
            source_documents=[old],
            staged_records=_records(old),
            health={"status": "healthy"},
            run_id="a-replay",
        )
        assert get_phase3_staged_record(candidate["id"]) == rejected
        changed = _document("b" * 64)
        merge_agenda_artifacts(
            source_documents=[changed],
            staged_records=_records(changed, status="Final"),
            health={"status": "healthy"},
            run_id="b",
        )
        health_rows = _read_collection("agenda_health")
        assert len(health_rows) == 1
        assert health_rows[0]["status"] == "degraded"
        assert health_rows[0]["identity_unresolved_count"] == 1
        unresolved = list_unresolved_observations()[0]
        before = {str(path): path.read_bytes() for path in tmp_path.rglob("*.json")}
        with pytest.raises(AgendaRevisionConflict):
            resolve_agenda_observation(
                unresolved["id"],
                candidate_id=candidate["id"],
                expected_observation_revision=1,
                expected_candidate_revision=1,
                actor="fixture",
                reason="Audited link",
            )
        assert before == {str(path): path.read_bytes() for path in tmp_path.rglob("*.json")}
        with monkeypatch.context() as failing_merge:

            def fail_after_resolution(*args: Any, **kwargs: Any) -> None:
                raise ValueError("injected validation failure")

            failing_merge.setattr(
                "app.ingestion.agenda_store._merge_candidate", fail_after_resolution
            )
            with pytest.raises(ValueError, match="injected validation failure"):
                resolve_agenda_observation(
                    unresolved["id"],
                    candidate_id=candidate["id"],
                    expected_observation_revision=1,
                    expected_candidate_revision=2,
                    actor="fixture",
                    reason="Audited link",
                )
        assert before == {str(path): path.read_bytes() for path in tmp_path.rglob("*.json")}
        resolved = resolve_agenda_observation(
            unresolved["id"],
            candidate_id=candidate["id"],
            expected_observation_revision=1,
            expected_candidate_revision=2,
            actor="fixture",
            reason="Audited link",
        )
        assert (
            resolved
            and resolved["content_revision"] == 2
            and resolved["review_status"] == "pending"
        )
        moved = _document("b" * 64, url="https://example.test/moved.pdf")
        merge_agenda_artifacts(
            source_documents=[moved],
            staged_records=[],
            health={"status": "healthy"},
            run_id="moved",
        )
        document_observation = list_unresolved_documents()[0]
        resolve_agenda_document_alias(
            document_observation["id"],
            document_id=resolved["source_payload"]["source_document_id"],
            expected_observation_revision=1,
            actor="fixture",
            reason="Same packet",
        )
        assert list_unresolved_documents() == []
        assert _read_collection("agenda_identity_resolutions")
        assert _read_collection("agenda_decision_events")[0]["notes"] == "Retain private note"
    finally:
        reset_phase3_state()
        get_settings.cache_clear()
