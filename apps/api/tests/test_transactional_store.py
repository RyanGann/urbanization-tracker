from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Phase3CollectionItem, ProcessedCollectionItem
from app.transactional_store import CollectionUnitOfWork


def test_item_upserts_preserve_other_rows_and_deterministic_order() -> None:
    engine = create_engine("sqlite://")
    Phase3CollectionItem.__table__.create(engine)
    ProcessedCollectionItem.__table__.create(engine)
    with Session(engine) as session:
        with session.begin():
            unit_of_work = CollectionUnitOfWork(session)
            unit_of_work.upsert_phase3(
                "public_submissions", "first", {"id": "first", "title": "First"}
            )
            unit_of_work.upsert_phase3(
                "public_submissions", "second", {"id": "second", "title": "Second"}
            )
            unit_of_work.upsert_phase3(
                "public_submissions", "first", {"id": "first", "title": "Updated"}
            )
            unit_of_work.upsert_processed(
                "development_records", "canonical-1", {"public_id": "canonical-1"}
            )

        assert unit_of_work.list_phase3("public_submissions") == [
            {"id": "first", "title": "Updated"},
            {"id": "second", "title": "Second"},
        ]
        assert unit_of_work.get_processed("development_records", "canonical-1") == {
            "public_id": "canonical-1"
        }
        session.rollback()  # Read queries autobegin; end that read-only transaction first.
        with session.begin():
            unit_of_work.delete_phase3("public_submissions", "first")

        assert unit_of_work.list_phase3("public_submissions") == [
            {"id": "second", "title": "Second"}
        ]
