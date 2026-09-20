from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from app.data_availability import Availability, CollectionRead, DataUnavailableError
from app.phase3_store import (
    _published_records_in_postgres_transaction,
    create_public_submission,
    list_public_submissions,
    reset_phase3_state,
)


def valid_record() -> dict[str, Any]:
    return {
        "public_id": "canonical-test-record",
        "title": "Canonical Test Record",
        "description": "Canonical record used to validate C02 mutation inputs.",
        "development_type": "subdivision",
        "status": "layout",
        "source_status": "layout",
        "source_url": "https://example.test/canonical",
        "source_agency": "Example Agency",
        "date_discovered": "2026-09-20",
        "date_last_checked": "2026-09-20",
        "review_status": "published",
        "confidence_level": "high",
        "geometry_source": "fixture",
        "geometry_confidence": "high",
        "geometry": {"type": "Point", "coordinates": [-86.6, 34.7]},
        "centroid": [-86.6, 34.7],
    }


def submission_payload() -> dict[str, Any]:
    return {
        "title": "C02 Explicit Empty Input",
        "source_url": "https://example.test/submission",
        "notes": "Submission used to verify C02 transaction boundaries.",
        "submitter_contact": "resident@example.test",
    }


@pytest.fixture(autouse=True)
def artifact_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("DATA_MODE", "live")
    monkeypatch.setenv("PHASE3_STORE_BACKEND", "artifact")
    monkeypatch.setenv("PROCESSED_STORE_BACKEND", "artifact")
    monkeypatch.setenv("INGESTION_DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    reset_phase3_state(force_memory=False)
    yield
    get_settings.cache_clear()
    reset_phase3_state(force_memory=True)


def test_explicit_empty_published_records_are_not_reloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_reload() -> list[Any]:
        raise AssertionError("explicit empty input must remain empty")

    monkeypatch.setattr("app.phase3_store._published_records_for_creation", unexpected_reload)
    create_public_submission(submission_payload(), published_records=[])

    assert [item["title"] for item in list_public_submissions()] == ["C02 Explicit Empty Input"]


def test_artifact_canonical_read_happens_before_any_submission_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> list[Any]:
        raise DataUnavailableError(
            collection="development_records", availability=Availability.UNAVAILABLE
        )

    monkeypatch.setattr("app.phase3_store._published_records_for_creation", unavailable)
    with pytest.raises(DataUnavailableError):
        create_public_submission(submission_payload())

    assert list_public_submissions() == []


class _UnitOfWork:
    def __init__(self, processed: list[dict[str, Any]], phase3: list[dict[str, Any]]) -> None:
        self.processed = processed
        self.phase3 = phase3

    def list_processed(self, _name: str) -> list[dict[str, Any]]:
        return self.processed

    def list_phase3(self, _name: str) -> list[dict[str, Any]]:
        return self.phase3


def test_postgres_creation_input_validates_both_canonical_collections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.phase3_store.get_settings", lambda: SimpleNamespace(processed_store_backend="postgres")
    )
    records = _published_records_in_postgres_transaction(_UnitOfWork([valid_record()], []))

    assert records[0].public_id == "canonical-test-record"

    with pytest.raises(DataUnavailableError):
        _published_records_in_postgres_transaction(_UnitOfWork([{"public_id": "broken"}], []))


def test_postgres_phase3_mutation_respects_artifact_processed_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.phase3_store.get_settings", lambda: SimpleNamespace(processed_store_backend="artifact")
    )
    monkeypatch.setattr(
        "app.processed_store.read_processed_list_result",
        lambda _name: CollectionRead(Availability.READY, [valid_record()]),
    )

    records = _published_records_in_postgres_transaction(_UnitOfWork([], []))

    assert records[0].public_id == "canonical-test-record"


def test_postgres_mutation_converts_database_failure_to_safe_availability_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingTransaction:
        def __enter__(self) -> Any:
            raise OperationalError("SELECT 1", {}, RuntimeError("database unavailable"))

        def __exit__(self, *_args: Any) -> None:
            return None

    class FailingSessionMaker:
        def begin(self) -> FailingTransaction:
            return FailingTransaction()

    monkeypatch.setattr("app.phase3_store._use_transactional_postgres", lambda: True)
    monkeypatch.setattr("app.db.SessionLocal", FailingSessionMaker())

    with pytest.raises(DataUnavailableError) as error:
        create_public_submission(submission_payload())

    assert error.value.availability is Availability.UNAVAILABLE
