"""C05 review policy across processed audit rows and operational candidates.

All state used by a decision/import is read after C02's transaction lock. The
artifact backend retains its documented local single-writer limitation.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.data_availability import Availability, DataUnavailableError
from app.ingestion.agenda_store import AgendaIdentityConflict, AgendaRevisionConflict

COLLECTIONS = {"agenda": "agenda_staged_records", "submission": "submission_staged_records"}
EVENTS = {"agenda": "agenda_decision_events", "submission": "review_decision_events"}
TRANSITIONS = {
    "pending": ("approved", "needs_info", "rejected"),
    "needs_info": ("approved", "needs_info", "rejected"),
}
ACTION_NAMES = {"approved": "approve", "rejected": "reject", "needs_info": "needs_info"}


class ReviewNotActionable(RuntimeError):
    """A known candidate cannot take the requested action."""


@contextmanager
def review_mutation() -> Iterator[Any]:
    from app.ingestion.agenda_store import _agenda_mutation

    try:
        with _agenda_mutation() as uow:
            yield uow
    except (SQLAlchemyError, ValidationError) as exc:
        raise DataUnavailableError(
            collection="review_records",
            availability=Availability.UNAVAILABLE,
        ) from exc


def revision(record: dict[str, Any]) -> int:
    return int(record.get("state_revision") or 0)


def legacy_history(record: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Disclose a retained legacy decision without inventing its actor or time."""
    if events or record["review_status"] == "pending":
        return events
    return [
        {
            "id": f"{record['id']}:legacy-baseline",
            "candidate_id": record["id"],
            "content_revision": record.get("content_revision") or 1,
            "state_revision": revision(record),
            "previous_status": None,
            "action": record["review_status"],
            "notes": record.get("review_notes"),
            "actor": record.get("review_actor") or "unknown_legacy",
            "decided_at": record.get("reviewed_at"),
            "baseline": True,
        }
    ]


def history(uow: Any, origin: str, staged_id: str) -> list[dict[str, Any]]:
    from app.schemas import ReviewHistoryEvent

    if origin not in EVENTS:
        return []
    events = sorted(
        [
            ReviewHistoryEvent.model_validate(e).model_dump()
            for e in uow.list_phase3(EVENTS[origin])
            if e["candidate_id"] == staged_id
        ],
        key=lambda e: e["state_revision"],
    )
    record = uow.get_phase3(COLLECTIONS[origin], staged_id)
    return legacy_history(record, events) if record is not None else events


def projection(
    record: dict[str, Any],
    origin: str,
    events: list[dict[str, Any]],
    public_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    row = copy.deepcopy(record)
    actions = list(TRANSITIONS.get(row["review_status"], ()))
    reason = "Manual candidate; decisions require the current revision."
    if origin == "processed":
        actions = []
        reason = (
            "Automatically ingested ArcGIS audit entry. Validated rows are published by "
            "ingestion; invalid candidates remain quarantined. Reviewer actions are unavailable."
        )
    elif not actions:
        reason = (
            "This revision has a final decision. A changed source needs a new candidate revision; "
            "published retraction requires the C06 publication workflow."
        )
    elif row.get("geometry") is None or row.get("location_required"):
        actions = [a for a in actions if a != "approved"]
        reason = (
            "A verified location is required before approval. Needs info or rejection is available."
        )
    if "approved" in actions and public_records is not None:
        from app.ingestion.source_merge import public_fingerprint
        from app.phase3_store import _publish_record_from_staged

        candidate = copy.deepcopy(row.get("publish_record") or _publish_record_from_staged(row))
        for key in ("geometry", "geometry_source", "geometry_confidence"):
            candidate[key] = row[key]
        existing = [r for r in public_records if r["public_id"] == candidate["public_id"]]
        if len(existing) > 1 or (
            existing and public_fingerprint(existing[0]) != public_fingerprint(candidate)
        ):
            actions.remove("approved")
            reason = (
                "An older published snapshot is retained. Changed publication requires C06; "
                "needs info or rejection can still review this candidate revision."
            )
    row.update(
        origin=origin,
        revision=revision(row),
        state_revision=revision(row),
        content_revision=row.get("content_revision") or 1,
        allowed_actions=[ACTION_NAMES[a] for a in actions],
        actionability_reason=reason,
        review_history=legacy_history(record, events) if origin != "processed" else events,
    )
    return row


def list_postgres_records() -> list[dict[str, Any]]:
    """Read queue and export snapshots without mixing concurrent review revisions."""
    with review_mutation() as uow:
        rows = [(row, "processed") for row in uow.list_processed("staged_development_records")]
        rows.extend(
            (row, origin) for origin, name in COLLECTIONS.items() for row in uow.list_phase3(name)
        )
        if len({row["id"] for row, _ in rows}) != len(rows):
            raise AgendaIdentityConflict("staged ID has ambiguous store ownership")
        events = {origin: uow.list_phase3(name) for origin, name in EVENTS.items()}
        public_records = [
            *uow.list_processed("development_records"),
            *uow.list_phase3("development_records"),
        ]
        return [
            projection(
                row,
                origin,
                sorted(
                    [e for e in events.get(origin, []) if e["candidate_id"] == row["id"]],
                    key=lambda e: e["state_revision"],
                ),
                public_records,
            )
            for row, origin in rows
        ]


def resolve(uow: Any, staged_id: str) -> tuple[str, dict[str, Any]] | None:
    matches = [
        (origin, row)
        for origin, collection in COLLECTIONS.items()
        if (row := uow.get_phase3(collection, staged_id)) is not None
    ]
    if get_settings().data_mode != "demo":
        if get_settings().processed_store_backend == "postgres":
            processed = uow.get_processed("staged_development_records", staged_id)
            rows = [processed] if processed is not None else []
        else:
            from app.processed_store import read_processed_list_result

            result = read_processed_list_result("staged_development_records")
            rows = (
                []
                if result.availability is Availability.UNINITIALIZED
                else result.require_ready(collection="staged_development_records")
            )
        matches.extend(("processed", row) for row in rows if row["id"] == staged_id)
    if len(matches) > 1:
        raise AgendaIdentityConflict("staged ID has ambiguous store ownership")
    return matches[0] if matches else None


def _check_revision(record: dict[str, Any], expected: int | None) -> None:
    if expected is None and get_settings().data_mode == "demo":
        return
    if expected is None or expected != revision(record):
        raise AgendaRevisionConflict("review revision changed")


def _apply(
    uow: Any,
    origin: str,
    record: dict[str, Any],
    *,
    action: str,
    notes: str | None,
    actor: str,
    decided_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from app.ingestion.agenda_store import publish_review_candidate

    if origin == "processed" or action not in TRANSITIONS.get(record["review_status"], ()):
        raise ReviewNotActionable("This revision does not allow that decision.")
    if action == "approved" and record.get("location_required"):
        raise ReviewNotActionable("A verified location is required before approval.")
    published = publish_review_candidate(uow, record, actor) if action == "approved" else None
    for event in history(uow, origin, record["id"]):
        if event.get("baseline") and uow.get_phase3(EVENTS[origin], event["id"]) is None:
            uow.upsert_phase3(EVENTS[origin], event["id"], event)
    previous = record["review_status"]
    record.update(
        review_status=action,
        review_notes=notes if notes is not None else record.get("review_notes"),
        review_actor=actor,
        reviewed_at=decided_at or datetime.now(UTC).isoformat(),
        state_revision=revision(record) + 1,
        content_revision=record.get("content_revision") or 1,
    )
    event = {
        "id": f"{record['id']}:{record['state_revision']}",
        "candidate_id": record["id"],
        "content_revision": record["content_revision"],
        "state_revision": record["state_revision"],
        "previous_status": previous,
        "action": action,
        "notes": record["review_notes"],
        "actor": actor,
        "decided_at": record["reviewed_at"],
    }
    if uow.get_phase3(EVENTS[origin], event["id"]) is not None:
        raise AgendaIdentityConflict("review event already exists")
    uow.upsert_phase3(EVENTS[origin], event["id"], event)
    uow.upsert_phase3(COLLECTIONS[origin], record["id"], record)
    if origin == "submission":
        submission_id = record.get("source_payload", {}).get("submission_id")
        submission = uow.get_phase3("public_submissions", submission_id) if submission_id else None
        if submission is not None:
            submission.update(status=action, review_notes=record["review_notes"])
            uow.upsert_phase3("public_submissions", submission_id, submission)
    return record, published


def decide(
    staged_id: str,
    *,
    action: str,
    notes: str | None,
    expected_revision: int | None,
    actor: str = "reviewer",
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    with review_mutation() as uow:
        found = resolve(uow, staged_id)
        if found is None:
            return None
        origin, record = found
        if action == "retracted":
            raise ReviewNotActionable("Retraction requires the deferred C06 publication workflow.")
        if origin == "processed":
            raise ReviewNotActionable(projection(record, origin, [])["actionability_reason"])
        _check_revision(record, expected_revision)
        result, published = _apply(uow, origin, record, action=action, notes=notes, actor=actor)
        public_records = None
        if result["review_status"] in TRANSITIONS:
            from app.ingestion.agenda_store import _processed_public_records

            public_records = [
                *_processed_public_records(uow),
                *uow.list_phase3("development_records"),
            ]
        return projection(
            result, origin, history(uow, origin, staged_id), public_records
        ), published


def import_one(decision: dict[str, Any]) -> str:
    """Apply one decision or append a validated backup suffix without replacing history."""
    staged_id = str(decision["staged_id"])
    with review_mutation() as uow:
        found = resolve(uow, staged_id)
        if found is None:
            return "missing"
        origin, record = found
        expected = decision.get("expected_revision")
        _check_revision(
            record, expected if expected is not None else decision.get("state_revision")
        )
        notes = decision.get("review_notes")
        if notes is None:
            notes = decision.get("notes")
        notes = notes if notes is not None else record.get("review_notes")
        action = decision["review_status"]
        current_history = history(uow, origin, staged_id)
        imported = decision.get("review_history")
        if imported is not None:
            target_revision = decision.get("state_revision")
            if (
                imported[: len(current_history)] != current_history
                or decision.get("content_revision") != (record.get("content_revision") or 1)
                or target_revision is None
                or target_revision < revision(record)
            ):
                raise AgendaRevisionConflict("backup differs from current review history")
            suffix = imported[len(current_history) :]
            # Validate the whole suffix before any side effects, including legacy/artifact mode.
            preview = copy.deepcopy(record)
            for event in suffix:
                if (
                    event.get("baseline")
                    or event.get("decided_at") is None
                    or event["candidate_id"] != staged_id
                    or event["id"] != f"{staged_id}:{event['state_revision']}"
                    or event["state_revision"] != revision(preview) + 1
                    or event["content_revision"] != (record.get("content_revision") or 1)
                    or event["previous_status"] != preview["review_status"]
                    or event["action"] not in TRANSITIONS.get(preview["review_status"], ())
                    or (event["notes"] is None and preview.get("review_notes") is not None)
                ):
                    raise AgendaRevisionConflict("backup suffix is not a legal continuation")
                preview.update(
                    state_revision=event["state_revision"],
                    review_status=event["action"],
                    review_notes=event["notes"],
                    review_actor=event["actor"],
                    reviewed_at=event["decided_at"],
                )
            if (
                revision(preview) != target_revision
                or preview["review_status"] != action
                or preview.get("review_notes") != notes
                or preview.get("review_actor") != decision.get("review_actor")
                or preview.get("reviewed_at") != decision.get("reviewed_at")
            ):
                raise AgendaRevisionConflict("backup snapshot does not match its history")
            if not suffix:
                return "unchanged"
            if origin == "processed":
                raise ReviewNotActionable("Ingestion audit rows are read-only.")
            for event in suffix:
                record, _ = _apply(
                    uow,
                    origin,
                    record,
                    action=event["action"],
                    notes=event["notes"],
                    actor=event["actor"],
                    decided_at=event["decided_at"],
                )
            return "applied"
        if action == record["review_status"] and notes == record.get("review_notes"):
            return "unchanged"
        _apply(uow, origin, record, action=action, notes=notes, actor="reviewer")
        return "applied"


def import_decisions(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    from fastapi import HTTPException

    from app.ingestion.agenda_store import AgendaPublicationPending

    result: dict[str, Any] = {"applied": 0, "missing": [], "conflicts": []}
    seen: set[str] = set()
    for decision in decisions:
        staged_id = str(decision["staged_id"])
        if staged_id in seen:
            result["conflicts"].append(staged_id)
            continue
        seen.add(staged_id)
        try:
            outcome = import_one(decision)
        except (
            AgendaRevisionConflict,
            AgendaIdentityConflict,
            AgendaPublicationPending,
            ReviewNotActionable,
            HTTPException,
        ):
            outcome = "conflicts"
        if outcome == "applied":
            result["applied"] += 1
        elif outcome != "unchanged":
            cast(list[str], result["missing" if outcome == "missing" else "conflicts"]).append(
                staged_id
            )
    return result
