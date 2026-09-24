"""C04 identity and decision-retention cases without external source refresh."""

from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any

from app.ingestion.agenda import parse_agenda_items
from app.ingestion.agenda_inventory import build_inventory
from app.ingestion.agenda_store import _digest, _merge_candidate, _merge_document


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
        "id": f"agenda-{sha[:12]}", "title": "Planning agenda April 28, 2026",
        "url": url, "document_date": "2026-04-28", "fetched_at": "2026-04-29T00:00:00Z",
        "sha256": sha, "text_sha256": sha, "extraction_status": "extracted",
        "pdf_reference_id": None, "text_reference_id": None,
    }


def _records(document: dict[str, Any], *, status: str = "Layout") -> list[dict[str, Any]]:
    return parse_agenda_items(
        f"1. SAMPLE RIDGE\n{status} (24 lots) Developer: Builder\nLocated: West of Road",
        source_document=document, checked_at="2026-04-29T00:00:00Z",
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
        uow, parsed, document_id=doc_id, revision_id=revision_id,
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
    assert _merge_candidate(
        uow, parsed, document_id=doc_id, revision_id=revision_id,
        document_date=document["document_date"],
    ) == candidate_id
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
        uow, original, document_id=doc_id, revision_id=old_revision,
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
    assert _merge_candidate(
        uow, new_observation, document_id=doc_id, revision_id=next_revision,
        document_date=changed["document_date"],
    ) is None
    # The initial revision also has an observation. Locate the new unresolved one.
    unresolved = next(
        item for item in uow.rows["agenda_observations"].values()
        if item["status"] == "identity_unresolved"
    )
    assert unresolved["candidate_id"] is None
    assert uow.get_phase3("agenda_staged_records", candidate_id)["review_status"] == "approved"
    assert len(uow.rows["agenda_candidate_revisions"]) == 1

    unresolved["candidate_id"] = candidate_id
    unresolved["status"] = "resolved"
    uow.upsert_phase3("agenda_observations", unresolved["id"], unresolved)
    assert _merge_candidate(
        uow, new_observation, document_id=doc_id, revision_id=next_revision,
        document_date=changed["document_date"],
    ) == candidate_id
    current = uow.get_phase3("agenda_staged_records", candidate_id)
    assert current and current["review_status"] == "pending"
    assert current["content_revision"] == 2
    assert len(uow.rows["agenda_candidate_revisions"]) == 2
    assert uow.rows["agenda_decision_events"][f"{candidate_id}:legacy-baseline"][
        "action"
    ] == "approved"


def test_same_legacy_title_id_cannot_link_across_document_revisions() -> None:
    uow = MemoryUow()
    document = _document("a" * 64)
    document_id, old_revision = _merge_document(uow, document, "old")
    assert document_id and old_revision
    record = _records(document)[0]
    candidate_id = _merge_candidate(
        uow, record, document_id=document_id, revision_id=old_revision,
        document_date=document["document_date"],
    )
    assert candidate_id
    newer = copy.deepcopy(record)
    newer["source_status"] = "Final"
    newer["normalized_status"] = "final"
    # A parser/extraction revision can retain the old title-derived legacy ID.
    # It is still a new unanchored observation, even if that ID resolves.
    assert _merge_candidate(
        uow, newer, document_id=document_id, revision_id="new-extraction-revision",
        document_date=document["document_date"],
    ) is None
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
    uow.upsert_phase3("agenda_document_aliases", alias_key, {
        "id": alias_key, "document_id": old_id, "url": moved["url"],
        "document_date": moved["document_date"],
    })
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
        uow, _records(document)[0], document_id=doc_id,
        revision_id=revision_id, document_date=document["document_date"],
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
        "document_alias": 1, "document_revision": 1,
        "candidate_revision": 1, "decision_baseline": 1,
    }
    assert result["samples"]["document_alias"] == ["legacy-doc"]
    assert result["samples"]["decision_baseline"] == ["reviewed"]
