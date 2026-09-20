"""Small shared unit of work for the generic durable collection tables.

The C02 pilot deliberately uses one transaction-scoped PostgreSQL advisory lock for
canonical and operational mutations.  Callers own the surrounding transaction;
this module never commits or rolls back a caller's session.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal, cast

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import Phase3CollectionItem, ProcessedCollectionItem

CollectionKind = Literal["phase3", "processed"]
CANONICAL_MUTATION_LOCK_NAMESPACE = 2088694651
CANONICAL_MUTATION_LOCK_KEY = 1
LOCK_TIMEOUT_MS = 1_500
STATEMENT_TIMEOUT_MS = 5_000


class MutationLockTimeout(RuntimeError):
    """A short canonical mutation lock wait expired before work began."""


class CollectionUnitOfWork:
    """Item-level reads and writes using one caller-provided SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def acquire_canonical_mutation_lock(self) -> None:
        """Set bounded local timeouts then acquire the documented transaction lock."""
        self.session.execute(
            text("SELECT set_config('lock_timeout', :timeout, true)"),
            {"timeout": f"{LOCK_TIMEOUT_MS}ms"},
        )
        self.session.execute(
            text("SELECT set_config('statement_timeout', :timeout, true)"),
            {"timeout": f"{STATEMENT_TIMEOUT_MS}ms"},
        )
        try:
            self.session.execute(
                text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
                {
                    "namespace": CANONICAL_MUTATION_LOCK_NAMESPACE,
                    "key": CANONICAL_MUTATION_LOCK_KEY,
                },
            )
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "55P03":
                raise MutationLockTimeout("canonical mutation lock timed out") from exc
            raise

    @contextmanager
    def canonical_mutation(self) -> Iterator[CollectionUnitOfWork]:
        self.acquire_canonical_mutation_lock()
        yield self

    def list_phase3(self, collection_name: str) -> list[dict[str, Any]]:
        return self._list("phase3", collection_name)

    def list_processed(self, collection_name: str) -> list[dict[str, Any]]:
        return self._list("processed", collection_name)

    def get_phase3(self, collection_name: str, item_id: str) -> dict[str, Any] | None:
        return self._get("phase3", collection_name, item_id)

    def get_processed(self, collection_name: str, item_id: str) -> dict[str, Any] | None:
        return self._get("processed", collection_name, item_id)

    def upsert_phase3(self, collection_name: str, item_id: str, payload: dict[str, Any]) -> None:
        self._upsert("phase3", collection_name, item_id, payload)

    def upsert_processed(self, collection_name: str, item_id: str, payload: dict[str, Any]) -> None:
        self._upsert("processed", collection_name, item_id, payload)

    def delete_phase3(self, collection_name: str, item_id: str) -> None:
        self._delete("phase3", collection_name, item_id)

    def delete_processed(self, collection_name: str, item_id: str) -> None:
        self._delete("processed", collection_name, item_id)

    def _model(
        self, kind: CollectionKind
    ) -> type[Phase3CollectionItem] | type[ProcessedCollectionItem]:
        return Phase3CollectionItem if kind == "phase3" else ProcessedCollectionItem

    def _list(self, kind: CollectionKind, collection_name: str) -> list[dict[str, Any]]:
        model = self._model(kind)
        rows = cast(
            list[Phase3CollectionItem | ProcessedCollectionItem],
            self.session.scalars(
                select(model)
                .where(model.collection_name == collection_name)
                .order_by(model.sort_order, model.id)
            ).all(),
        )
        return [copy.deepcopy(row.payload_json) for row in rows]

    def _get(
        self, kind: CollectionKind, collection_name: str, item_id: str
    ) -> dict[str, Any] | None:
        model = self._model(kind)
        row = cast(
            Phase3CollectionItem | ProcessedCollectionItem | None,
            self.session.scalar(
                select(model).where(
                    model.collection_name == collection_name,
                    model.item_id == item_id,
                )
            ),
        )
        return copy.deepcopy(row.payload_json) if row is not None else None

    def _upsert(
        self, kind: CollectionKind, collection_name: str, item_id: str, payload: dict[str, Any]
    ) -> None:
        model = self._model(kind)
        row = cast(
            Phase3CollectionItem | ProcessedCollectionItem | None,
            self.session.scalar(
                select(model).where(
                    model.collection_name == collection_name,
                    model.item_id == item_id,
                )
            ),
        )
        if row is not None:
            row.payload_json = copy.deepcopy(payload)
            return
        next_sort_order = self.session.scalar(
            select(func.coalesce(func.max(model.sort_order), -1)).where(
                model.collection_name == collection_name
            )
        )
        self.session.add(
            model(
                collection_name=collection_name,
                item_id=item_id,
                sort_order=int(-1 if next_sort_order is None else next_sort_order) + 1,
                payload_json=copy.deepcopy(payload),
            )
        )
        self.session.flush()

    def _delete(self, kind: CollectionKind, collection_name: str, item_id: str) -> None:
        model = self._model(kind)
        self.session.execute(
            delete(model).where(
                model.collection_name == collection_name,
                model.item_id == item_id,
            )
        )
