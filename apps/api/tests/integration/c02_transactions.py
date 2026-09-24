"""Real HTTP/PostgreSQL checks for C02's locked public creation paths."""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sqlalchemy import func, select, text

from app.db import SessionLocal, engine
from app.models import Phase3CollectionItem
from app.phase3_store import create_public_submission, create_watch_area
from app.transactional_store import (
    CANONICAL_MUTATION_LOCK_KEY,
    CANONICAL_MUTATION_LOCK_NAMESPACE,
    CollectionUnitOfWork,
)


def request_json(
    api_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    reviewer_token: str | None = None,
) -> tuple[int, dict[str, Any] | list[Any], dict[str, str]]:
    headers = {"Accept": "application/json"}
    if reviewer_token is not None:
        headers["Authorization"] = f"Bearer {reviewer_token}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{api_url}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 -- controlled integration URL
            return response.status, json.loads(response.read()), dict(response.headers.items())
    except HTTPError as error:
        return error.code, json.loads(error.read()), dict(error.headers.items())


def submission_payload(title: str) -> dict[str, Any]:
    return {
        "title": title,
        "source_url": "https://example.test/c02",
        "notes": "C02 transaction scenario submission for durable concurrent creation.",
        "submitter_contact": f"{title.lower().replace(' ', '-')}@example.test",
    }


def watch_payload(name: str, email: str) -> dict[str, Any]:
    return {
        "name": name,
        "email": email,
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[-86.8, 34.5], [-86.4, 34.5], [-86.4, 34.9], [-86.8, 34.9], [-86.8, 34.5]]
            ],
        },
        "filters": {},
    }


def concurrent_posts(
    api_url: str, path: str, payloads: list[dict[str, Any]]
) -> list[tuple[int, dict[str, Any] | list[Any], dict[str, str]]]:
    barrier = threading.Barrier(len(payloads) + 1)
    results: list[tuple[int, dict[str, Any] | list[Any], dict[str, str]] | None] = [None] * len(
        payloads
    )

    def send(index: int, payload: dict[str, Any]) -> None:
        barrier.wait(timeout=10)
        results[index] = request_json(api_url, path, method="POST", payload=payload)

    threads = [
        threading.Thread(target=send, args=(index, payload))
        for index, payload in enumerate(payloads)
    ]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=10)
    for thread in threads:
        thread.join(timeout=15)
    if any(thread.is_alive() for thread in threads) or any(result is None for result in results):
        raise AssertionError(f"concurrent {path} requests did not complete")
    return [result for result in results if result is not None]


def assert_postgres_item_upsert() -> None:
    """Prove the real unique constraint updates one item without replacing siblings."""
    collection_name = "c02_uow_item_upsert"
    first_payload = {"title": "first"}
    second_payload = {"title": "second"}
    updated_first_payload = {"title": "first updated"}

    # SessionLocal uses autoflush=False in production.  Exercise that exact setting
    # against PostgreSQL rather than relying only on the SQLite helper unit test.
    with SessionLocal.begin() as session:
        unit_of_work = CollectionUnitOfWork(session)
        with unit_of_work.canonical_mutation():
            unit_of_work.upsert_phase3(collection_name, "first", first_payload)
            unit_of_work.upsert_phase3(collection_name, "second", second_payload)
            unit_of_work.upsert_phase3(collection_name, "first", updated_first_payload)

    with SessionLocal() as session:
        unit_of_work = CollectionUnitOfWork(session)
        rows = unit_of_work.list_phase3(collection_name)
        first_row_count = session.scalar(
            select(func.count(Phase3CollectionItem.id)).where(
                Phase3CollectionItem.collection_name == collection_name,
                Phase3CollectionItem.item_id == "first",
            )
        )
    if rows != [updated_first_payload, second_payload] or first_row_count != 1:
        raise AssertionError(
            "item upsert did not preserve one updated row and its unrelated sibling order"
        )


def assert_creation_phase(
    api_url: str, reviewer_token: str, fixture_id: str, result_path: Path
) -> list[str]:
    assert_postgres_item_upsert()
    prefix = result_path.parent.name.replace("-data", "")
    submission_titles = [
        f"{prefix} concurrent submission one",
        f"{prefix} concurrent submission two",
    ]
    submission_results = concurrent_posts(
        api_url,
        "/api/public-submissions",
        [submission_payload(title) for title in submission_titles],
    )
    if [status for status, _, _ in submission_results] != [200, 200]:
        raise AssertionError(f"concurrent submissions failed: {submission_results!r}")
    submission_ids = [
        str(body["id"]) for _, body, _ in submission_results if isinstance(body, dict)
    ]

    staged_status, staged_body, _ = request_json(
        api_url, "/api/reviewer/staged-records", reviewer_token=reviewer_token
    )
    if staged_status != 200 or not isinstance(staged_body, list):
        raise AssertionError(
            f"reviewer staged records unavailable: {staged_status} {staged_body!r}"
        )
    staged_submission_ids = {
        str(item.get("source_payload", {}).get("submission_id"))
        for item in staged_body
        if isinstance(item, dict)
    }
    if not set(submission_ids).issubset(staged_submission_ids):
        raise AssertionError("concurrent submissions did not both persist their staged records")

    watch_names = [f"{prefix} concurrent watch one", f"{prefix} concurrent watch two"]
    watch_results = concurrent_posts(
        api_url,
        "/api/watch-areas",
        [watch_payload(name, f"{index}@example.test") for index, name in enumerate(watch_names)],
    )
    if [status for status, _, _ in watch_results] != [200, 200]:
        raise AssertionError(f"concurrent watch creation failed: {watch_results!r}")
    watch_ids = [str(body["id"]) for _, body, _ in watch_results if isinstance(body, dict)]

    watches_status, watches_body, _ = request_json(
        api_url, "/api/reviewer/watch-areas", reviewer_token=reviewer_token
    )
    if watches_status != 200 or not isinstance(watches_body, list):
        raise AssertionError(f"reviewer watches unavailable: {watches_status} {watches_body!r}")
    if not set(watch_ids).issubset(
        {str(item["id"]) for item in watches_body if isinstance(item, dict)}
    ):
        raise AssertionError("concurrent watches did not both persist")
    alerts_status, alerts_body, _ = request_json(
        api_url, "/api/reviewer/alerts", reviewer_token=reviewer_token
    )
    if alerts_status != 200 or not isinstance(alerts_body, list):
        raise AssertionError(f"reviewer alerts unavailable: {alerts_status} {alerts_body!r}")
    alert_ids = [
        str(item["id"])
        for item in alerts_body
        if isinstance(item, dict) and str(item.get("watch_area_id")) in watch_ids
    ]
    if not all(
        any(
            str(item.get("watch_area_id")) == watch_id
            for item in alerts_body
            if isinstance(item, dict)
        )
        for watch_id in watch_ids
    ):
        raise AssertionError("concurrent watches did not both persist their initial alerts")

    records_status, records_body, _ = request_json(api_url, "/api/development-records")
    if records_status != 200 or not isinstance(records_body, dict):
        raise AssertionError(f"canonical read unavailable during C02 scenario: {records_status}")
    if fixture_id not in {str(item.get("public_id")) for item in records_body.get("records", [])}:
        raise AssertionError("C02 creation replaced the unrelated canonical fixture")

    failed_title = f"{prefix} rollback sentinel"

    def fail_after_staged(point: str) -> None:
        if point == "submission_staged_written":
            raise RuntimeError(point)

    try:
        create_public_submission(
            submission_payload(failed_title),
            _failure_injector=fail_after_staged,
        )
    except RuntimeError as error:
        if str(error) != "submission_staged_written":
            raise
    else:
        raise AssertionError("injected submission boundary failure did not raise")
    submissions_status, submissions_body, _ = request_json(
        api_url, "/api/reviewer/submissions", reviewer_token=reviewer_token
    )
    if submissions_status != 200 or not isinstance(submissions_body, list):
        raise AssertionError("reviewer submissions unavailable after rollback injection")
    if failed_title in {
        str(item.get("title")) for item in submissions_body if isinstance(item, dict)
    }:
        raise AssertionError("rollback left a partial public submission receipt")
    staged_status, staged_after_rollback, _ = request_json(
        api_url, "/api/reviewer/staged-records", reviewer_token=reviewer_token
    )
    if staged_status != 200 or not isinstance(staged_after_rollback, list):
        raise AssertionError("reviewer staged records unavailable after rollback injection")
    if any(
        item.get("source_payload", {}).get("submission_id")
        for item in staged_after_rollback
        if isinstance(item, dict) and item.get("title") == failed_title
    ):
        raise AssertionError("rollback left a partial staged submission row")

    failed_watch_name = f"{prefix} rollback watch sentinel"

    def fail_after_alerts(point: str) -> None:
        if point == "watch_alerts_written":
            raise RuntimeError(point)

    try:
        create_watch_area(
            watch_payload(failed_watch_name, "rollback-watch@example.test"),
            _failure_injector=fail_after_alerts,
        )
    except RuntimeError as error:
        if str(error) != "watch_alerts_written":
            raise
    else:
        raise AssertionError("injected watch boundary failure did not raise")
    watches_status, watches_after_rollback, _ = request_json(
        api_url, "/api/reviewer/watch-areas", reviewer_token=reviewer_token
    )
    alerts_status, alerts_after_rollback, _ = request_json(
        api_url, "/api/reviewer/alerts", reviewer_token=reviewer_token
    )
    if watches_status != 200 or alerts_status != 200:
        raise AssertionError("reviewer collections unavailable after watch rollback injection")
    if any(
        isinstance(item, dict) and item.get("name") == failed_watch_name
        for item in watches_after_rollback
    ) or any(
        isinstance(item, dict) and failed_watch_name in str(item.get("summary"))
        for item in alerts_after_rollback
    ):
        raise AssertionError("watch rollback left a partial watch or alert row")

    with engine.connect() as holder:
        transaction = holder.begin()
        try:
            holder.execute(
                text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
                {
                    "namespace": CANONICAL_MUTATION_LOCK_NAMESPACE,
                    "key": CANONICAL_MUTATION_LOCK_KEY,
                },
            )
            read_status, _, _ = request_json(api_url, "/api/development-records")
            if read_status != 200:
                raise AssertionError(f"unrelated read was blocked by mutation lock: {read_status}")
            lock_status, lock_body, lock_headers = request_json(
                api_url,
                "/api/public-submissions",
                method="POST",
                payload=submission_payload(f"{prefix} lock timeout"),
            )
            if lock_status != 503 or not isinstance(lock_body, dict):
                raise AssertionError(
                    f"bounded lock did not return 503: {lock_status} {lock_body!r}"
                )
            detail = lock_body.get("detail")
            serialized = json.dumps(lock_body).lower()
            retry_after = next(
                (value for key, value in lock_headers.items() if key.lower() == "retry-after"), None
            )
            if (
                not isinstance(detail, dict)
                or detail.get("code") != "transaction_busy"
                or retry_after != "1"
                or "postgres" in serialized
                or "integration:" in serialized
            ):
                raise AssertionError(
                    f"lock timeout leaked or changed its safe contract: {lock_body!r}"
                )
        finally:
            transaction.rollback()

    unlocked_status, unlocked_body, _ = request_json(
        api_url,
        "/api/public-submissions",
        method="POST",
        payload=submission_payload(f"{prefix} lock released"),
    )
    if unlocked_status != 200 or not isinstance(unlocked_body, dict):
        raise AssertionError(f"mutation did not recover after lock release: {unlocked_status}")

    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            {
                "submission_titles": submission_titles,
                "submission_ids": submission_ids,
                "watch_ids": watch_ids,
                "alert_ids": alert_ids,
                "fixture_id": fixture_id,
                "checks": [
                    "postgres-item-upsert:one-row-and-sibling-order-preserved",
                    "concurrent-submissions:both-receipts-and-staged-rows",
                    "concurrent-watches:both-receipts",
                    "concurrent-watches:initial-alerts",
                    "unrelated-canonical-row:preserved",
                    "injected-dependent-write:rolled-back",
                    "injected-watch-and-alert-write:rolled-back",
                    "held-advisory-lock:bounded-safe-503",
                    "unrelated-read:available",
                    "released-lock:mutation-recovers",
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return ["creation-and-lock-checks:passed"]


def assert_persistence(api_url: str, reviewer_token: str, result_path: Path) -> list[str]:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    status, body, _ = request_json(
        api_url, "/api/reviewer/submissions", reviewer_token=reviewer_token
    )
    titles = (
        {str(item.get("title")) for item in body if isinstance(item, dict)}
        if isinstance(body, list)
        else set()
    )
    if status != 200 or not set(result["submission_titles"]).issubset(titles):
        raise AssertionError("restart did not preserve concurrent C02 submissions")
    staged_status, staged_body, _ = request_json(
        api_url, "/api/reviewer/staged-records", reviewer_token=reviewer_token
    )
    staged_submission_ids = (
        {
            str(item.get("source_payload", {}).get("submission_id"))
            for item in staged_body
            if isinstance(item, dict)
        }
        if isinstance(staged_body, list)
        else set()
    )
    if staged_status != 200 or not set(result["submission_ids"]).issubset(staged_submission_ids):
        raise AssertionError("restart did not preserve concurrent C02 staged rows")
    watches_status, watches_body, _ = request_json(
        api_url, "/api/reviewer/watch-areas", reviewer_token=reviewer_token
    )
    persisted_watch_ids = (
        {str(item.get("id")) for item in watches_body if isinstance(item, dict)}
        if isinstance(watches_body, list)
        else set()
    )
    if watches_status != 200 or not set(result["watch_ids"]).issubset(persisted_watch_ids):
        raise AssertionError("restart did not preserve concurrent C02 watches")
    alerts_status, alerts_body, _ = request_json(
        api_url, "/api/reviewer/alerts", reviewer_token=reviewer_token
    )
    persisted_alert_ids = (
        {str(item.get("id")) for item in alerts_body if isinstance(item, dict)}
        if isinstance(alerts_body, list)
        else set()
    )
    if alerts_status != 200 or not set(result["alert_ids"]).issubset(persisted_alert_ids):
        raise AssertionError("restart did not preserve concurrent C02 alerts")
    return ["restart-persistence:passed"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--reviewer-token", required=True)
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--phase", choices=("create", "verify"), required=True)
    args = parser.parse_args()
    result_path = Path(args.result)
    checks = (
        assert_creation_phase(args.api_url, args.reviewer_token, args.fixture_id, result_path)
        if args.phase == "create"
        else assert_persistence(args.api_url, args.reviewer_token, result_path)
    )
    print(json.dumps({"phase": args.phase, "checks": checks}))


if __name__ == "__main__":
    main()
