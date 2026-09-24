"""Read-only inventory of agenda rows needing an explicit C04b backfill.

Run ``python -m app.ingestion.agenda_inventory`` with the API environment
configured for the target store. No source fetch or database write occurs.
"""

from __future__ import annotations

import json
from typing import Any


def build_inventory(
    *, documents: list[dict[str, Any]], candidates: list[dict[str, Any]],
    aliases: list[dict[str, Any]], document_revisions: list[dict[str, Any]],
    candidate_revisions: list[dict[str, Any]], decision_events: list[dict[str, Any]],
    sample_limit: int = 50,
) -> dict[str, Any]:
    """Report missing history; never derive a replacement identity from text."""
    aliased_documents = {str(row.get("document_id")) for row in aliases}
    revisioned_documents = {str(row.get("document_id")) for row in document_revisions}
    revisioned_candidates = {str(row.get("candidate_id")) for row in candidate_revisions}
    decided_candidates = {str(row.get("candidate_id")) for row in decision_events}
    missing: dict[str, list[str]] = {
        "document_alias": [], "document_revision": [],
        "candidate_revision": [], "decision_baseline": [],
    }
    for row in documents:
        document_id = str(row["id"])
        if document_id not in aliased_documents:
            missing["document_alias"].append(document_id)
        if document_id not in revisioned_documents:
            missing["document_revision"].append(document_id)
    for row in candidates:
        candidate_id = str(row["id"])
        if candidate_id not in revisioned_candidates:
            missing["candidate_revision"].append(candidate_id)
        if row.get("review_status") not in (None, "pending") and (
            candidate_id not in decided_candidates
        ):
            missing["decision_baseline"].append(candidate_id)
    return {
        "read_only": True,
        "documents_seen": len(documents),
        "candidates_seen": len(candidates),
        "missing_counts": {key: len(value) for key, value in missing.items()},
        "samples": {key: sorted(value)[:sample_limit] for key, value in missing.items()},
        "samples_truncated": {
            key: len(value) > sample_limit for key, value in missing.items()
        },
    }


def main() -> None:
    from app.config import get_settings
    from app.phase3_store import _read_collection

    names = (
        "source_documents", "agenda_staged_records", "agenda_document_aliases",
        "agenda_document_revisions", "agenda_candidate_revisions",
        "agenda_decision_events",
    )
    rows = {name: _read_collection(name) for name in names}
    result = build_inventory(
        documents=rows["source_documents"],
        candidates=rows["agenda_staged_records"],
        aliases=rows["agenda_document_aliases"],
        document_revisions=rows["agenda_document_revisions"],
        candidate_revisions=rows["agenda_candidate_revisions"],
        decision_events=rows["agenda_decision_events"],
    )
    settings = get_settings()
    result["data_mode"] = settings.data_mode
    result["phase3_store_backend"] = settings.phase3_store_backend
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
