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

    def delete_phase3(self, collection: str, key: str) -> None:
        self.rows[collection].pop(key, None)

    def list_processed(self, collection: str) -> list[dict[str, Any]]:
        return copy.deepcopy(list(self.rows[f"processed:{collection}"].values()))

    def get_processed(self, collection: str, key: str) -> dict[str, Any] | None:
        value = self.rows[f"processed:{collection}"].get(key)
        return copy.deepcopy(value) if value is not None else None


@pytest.mark.parametrize("ownership", ["processed", "changed", "ambiguous"])
def test_approval_preserves_processed_public_ownership(ownership: str, monkeypatch: Any) -> None:
    from contextlib import contextmanager

    from app.ingestion.agenda_store import (
        AgendaIdentityConflict,
        AgendaPublicationPending,
        review_agenda_candidate,
    )

    uow = MemoryUow()
    public = {
        "public_id": "existing-public",
        "title": "Sample Ridge",
        "geometry": {"type": "Point", "coordinates": [-86.6, 34.7]},
        "centroid": [-86.6, 34.7],
        "geometry_source": "reviewer",
        "geometry_confidence": "high",
        "source_fields": {},
        "review_status": "published",
        "date_last_checked": "2026-01-01",
    }
    candidate = {
        "id": "candidate",
        "state_revision": 1,
        "content_revision": 1,
        "review_status": "pending",
        "publish_record": copy.deepcopy(public),
        **{
            key: public[key]
            for key in ("geometry", "centroid", "geometry_source", "geometry_confidence")
        },
    }
    if ownership == "changed":
        candidate["publish_record"]["title"] = "Changed Ridge"
    uow.upsert_phase3("agenda_staged_records", "candidate", candidate)
    uow.rows["processed:development_records"]["existing-public"] = copy.deepcopy(public)
    if ownership == "ambiguous":
        uow.upsert_phase3("development_records", "existing-public", public)
    before = copy.deepcopy(uow.rows)

    @contextmanager
    def mutation() -> Any:
        yield uow

    monkeypatch.setattr("app.ingestion.agenda_store._agenda_mutation", mutation)
    monkeypatch.setattr("app.public_geometry.require_publishable_geometry", lambda record: None)
    if ownership == "processed":
        result = review_agenda_candidate(
            "candidate", action="approved", notes="Reviewed", expected_revision=1
        )
        assert result is not None and result[1] == public
        assert not uow.rows["development_records"]
        assert not uow.rows["record_versions"]
        assert not uow.rows["change_log"]
        assert len(uow.rows["agenda_decision_events"]) == 1
    else:
        error = AgendaIdentityConflict if ownership == "ambiguous" else AgendaPublicationPending
        with pytest.raises(error):
            review_agenda_candidate(
                "candidate", action="approved", notes="Reviewed", expected_revision=1
            )
        assert all(uow.rows[key] == value for key, value in before.items())
        assert not uow.rows["agenda_decision_events"]
    assert uow.rows["processed:development_records"]["existing-public"] == public


def test_import_classifies_ambiguous_public_ownership_as_conflict(monkeypatch: Any) -> None:
    from app.ingestion.agenda_store import AgendaIdentityConflict
    from app.seed_store import import_reviewer_decisions

    monkeypatch.setattr(
        "app.phase3_store.get_phase3_staged_record",
        lambda staged_id: {"state_revision": 1, "review_status": "pending"},
    )

    def approve(*args: Any, **kwargs: Any) -> None:
        raise AgendaIdentityConflict("public record has ambiguous store ownership")

    monkeypatch.setattr("app.seed_store.approve_staged_record", approve)
    assert import_reviewer_decisions(
        [{"staged_id": "stage-agenda-owned", "review_status": "approved", "expected_revision": 1}]
    ) == {"applied": 0, "missing": [], "conflicts": ["stage-agenda-owned"]}


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


def test_duplicate_refresh_reads_processed_public_rows_and_preserves_audited_rows() -> None:
    from app.ingestion.agenda_store import _refresh_duplicate_suggestions
    from app.phase3_store import _stable_id

    uow = MemoryUow()
    uow.rows["processed:development_records"]["processed-public"] = {
        "public_id": "processed-public",
        "title": "Sample Ridge",
        "status": "layout",
    }
    uow.upsert_phase3(
        "agenda_staged_records",
        "candidate",
        {
            "id": "candidate",
            "title": "Sample Ridge",
            "normalized_status": "layout",
        },
    )
    _refresh_duplicate_suggestions(uow, {"candidate"})
    suggestion_id = _stable_id("duplicate", "candidate", "processed-public")
    assert uow.get_phase3("duplicate_candidates", suggestion_id)
    audited_id = _stable_id("duplicate", "candidate", "audited-public")
    audited = {
        "id": audited_id,
        "staged_record_id": "candidate",
        "candidate_public_id": "audited-public",
        "review_actor": "reviewer",
        "decision": "confirmed",
    }
    unrelated = {"id": "unrelated", "staged_record_id": "other"}
    uow.upsert_phase3("duplicate_candidates", audited_id, audited)
    uow.upsert_phase3("duplicate_candidates", "unrelated", unrelated)
    uow.upsert_phase3(
        "agenda_staged_records",
        "candidate",
        {
            "id": "candidate",
            "title": "Unrelated Valley",
            "normalized_status": "layout",
        },
    )
    _refresh_duplicate_suggestions(uow, {"candidate"})
    assert uow.get_phase3("duplicate_candidates", suggestion_id) is None
    assert uow.get_phase3("duplicate_candidates", audited_id) == audited
    assert uow.get_phase3("duplicate_candidates", "unrelated") == unrelated


def test_dateless_moved_historical_checksum_requires_alias_without_state_changes() -> None:
    from app.ingestion.agenda_store import _existing_document, _merge_agenda_batch

    uow = MemoryUow()
    first = {**_document("a" * 64), "document_date": None}
    _merge_agenda_batch(uow, [first], _records(first), {"status": "healthy"}, "a")
    candidate = uow.list_phase3("agenda_staged_records")[0]
    candidate.update(review_status="rejected", review_notes="Retain historical decision")
    uow.upsert_phase3("agenda_staged_records", candidate["id"], candidate)
    changed = {**_document("b" * 64), "document_date": None}
    _merge_agenda_batch(uow, [changed], [], {"status": "healthy"}, "b")
    latest = uow.list_phase3("source_documents")
    moved = {**first, "url": "https://example.test/moved.pdf"}
    assert _existing_document(uow, moved) == (None, True)
    _merge_agenda_batch(uow, [moved], _records(moved), {"status": "healthy"}, "moved")
    assert uow.list_phase3("source_documents") == latest
    assert uow.get_phase3("agenda_staged_records", candidate["id"]) == candidate
    assert len(uow.list_phase3("agenda_unresolved_documents")) == 1
    assert _existing_document(uow, {**moved, "sha256": ""}) == (None, False)
    assert _existing_document(uow, {**moved, "sha256": None}) == (None, False)


def test_partial_pending_artifact_persists_health_without_activating_content(
    tmp_path: Any, monkeypatch: Any
) -> None:
    import httpx

    from app.config import get_settings
    from app.ingestion.agenda_pipeline import ingest_huntsville_agendas
    from app.ingestion.agenda_store import SOURCE_KEY, merge_agenda_artifacts
    from app.ingestion.artifact_sink import ArtifactError
    from app.ingestion.connectors.agenda import AgendaLink
    from app.phase3_store import _read_collection, reset_phase3_state

    for name, value in {
        "INGESTION_DATA_DIR": str(tmp_path),
        "DATA_MODE": "live",
        "PHASE3_STORE_BACKEND": "artifact",
        "PROCESSED_STORE_BACKEND": "artifact",
        "ARTIFACT_DURABILITY_REQUIRED": "false",
        "HOSTED_INGESTION_ENABLED": "false",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    reset_phase3_state(force_memory=False)
    try:
        first = _document("a" * 64)
        merge_agenda_artifacts(
            source_documents=[first],
            staged_records=_records(first),
            health={"key": SOURCE_KEY, "status": "healthy", "checked_at": "2026-09-26T00:00:00Z"},
        )
        names = ("source_documents", "agenda_staged_records", "agenda_document_revisions")
        before = {name: _read_collection(name) for name in names}
        fresh = {**_document("b" * 64), "parsed_item_count": 1}

        def parse(**kwargs: Any) -> tuple:
            if kwargs["url"].endswith("pending.pdf"):
                raise ArtifactError("artifact_unavailable")
            return fresh, _records(fresh), []

        monkeypatch.setattr(
            "app.ingestion.agenda_pipeline._fetch_archive_html",
            lambda client: ("<html>synthetic archive</html>", "httpx_archive"),
        )
        monkeypatch.setattr(
            "app.ingestion.agenda_pipeline.discover_agenda_links",
            lambda *a, **k: [
                AgendaLink(title="Valid", url="https://example.test/valid.pdf"),
                AgendaLink(title="Pending", url="https://example.test/pending.pdf"),
            ],
        )
        monkeypatch.setattr("app.ingestion.agenda_pipeline._fetch_and_parse_document", parse)
        monkeypatch.setattr("app.ingestion.agenda_pipeline.iso_now", lambda: "2026-09-27T00:00:00Z")
        with httpx.Client() as client:
            health = ingest_huntsville_agendas(data_dir=tmp_path, client=client)
        assert health["documents_seen"] == 1 and health["status"] == "degraded"
        assert health["last_attempt_at"] == "2026-09-27T00:00:00Z"
        assert health["last_success_at"] == "2026-09-26T00:00:00Z"
        assert _read_collection("agenda_health") == [health]
        assert {name: _read_collection(name) for name in names} == before
    finally:
        reset_phase3_state(force_memory=False)
        get_settings.cache_clear()


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
