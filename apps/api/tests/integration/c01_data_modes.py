"""Real-HTTP assertions for C01 availability modes; invoked by the T01 Compose runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(
    api_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    reviewer_token: str | None = None,
) -> tuple[int, Any]:
    headers: dict[str, str] = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if reviewer_token:
        headers["Authorization"] = f"Bearer {reviewer_token}"
    request_value = Request(f"{api_url}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request_value, timeout=10) as response:  # noqa: S310 - test fixture URL
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def assert_status(actual: int, expected: int, path: str) -> None:
    if actual != expected:
        raise AssertionError(f"{path}: expected HTTP {expected}, got {actual}")


def assert_unavailable(api_url: str, availability: str) -> list[str]:
    checks: list[str] = []
    status, body = request(api_url, "/api/dataset-status")
    assert_status(status, 200, "/api/dataset-status")
    if body.get("data_mode") != "live" or body.get("availability") != availability:
        raise AssertionError(f"dataset status did not report live/{availability}: {body!r}")
    checks.append(f"dataset-status:{availability}")
    for path in (
        "/api/development-records",
        "/api/development-records/not-a-real-record",
        "/api/map/development-records.geojson",
    ):
        status, body = request(api_url, path)
        assert_status(status, 503, path)
        if body.get("detail", {}).get("code") != "data_unavailable":
            raise AssertionError(f"{path}: missing stable data_unavailable code: {body!r}")
        checks.append(f"{path}:503")
    return checks


def assert_empty_ready(api_url: str) -> list[str]:
    checks: list[str] = []
    status, body = request(api_url, "/api/dataset-status")
    assert_status(status, 200, "/api/dataset-status")
    if body.get("data_mode") != "live" or body.get("availability") != "ready":
        raise AssertionError(f"dataset status did not report ready live data: {body!r}")
    checks.append("dataset-status:ready")
    status, body = request(api_url, "/api/development-records")
    assert_status(status, 200, "/api/development-records")
    if body.get("data_mode") != "live" or body.get("records") != []:
        raise AssertionError(f"live empty collection was not preserved: {body!r}")
    checks.append("records:empty")
    status, _body = request(api_url, "/api/development-records/not-a-real-record")
    assert_status(status, 404, "/api/development-records/not-a-real-record")
    checks.append("detail:404")
    status, body = request(api_url, "/api/map/development-records.geojson")
    assert_status(status, 200, "/api/map/development-records.geojson")
    if body.get("data_mode") != "live" or body.get("features") != []:
        raise AssertionError(f"empty GeoJSON was not preserved: {body!r}")
    checks.append("geojson:empty")
    return checks


def assert_fixture(api_url: str, fixture_id: str) -> list[str]:
    status, body = request(api_url, "/api/development-records")
    assert_status(status, 200, "/api/development-records")
    if body.get("data_mode") != "live" or not any(
        record.get("public_id") == fixture_id for record in body.get("records", [])
    ):
        raise AssertionError(f"expected restored real Postgres fixture {fixture_id}: {body!r}")
    return ["fixture:restored"]


def assert_demo(api_url: str, fixture_id: str) -> list[str]:
    status, body = request(api_url, "/api/dataset-status")
    assert_status(status, 200, "/api/dataset-status")
    if body.get("data_mode") != "demo" or body.get("availability") != "ready":
        raise AssertionError(f"dataset status did not report ready demo data: {body!r}")
    status, body = request(api_url, "/api/development-records")
    assert_status(status, 200, "/api/development-records")
    records = body.get("records", [])
    if body.get("data_mode") != "demo" or not records:
        raise AssertionError(f"demo records were not explicit and nonempty: {body!r}")
    if any(record.get("public_id") == fixture_id for record in records):
        raise AssertionError("demo response mixed the live Postgres fixture")
    return ["dataset-status:demo-ready", "records:demo-nonempty", "fixture:not-mixed"]


def _create_submission(api_url: str, title: str) -> None:
    status, body = request(
        api_url,
        "/api/public-submissions",
        method="POST",
        payload={
            "title": title,
            "source_url": "https://example.test/c01-data-modes",
            "notes": "C01 real-stack demo isolation verification submission.",
            "submitter_contact": "c01-integration@example.test",
        },
    )
    assert_status(status, 200, "/api/public-submissions")
    if body.get("title") != title:
        raise AssertionError(f"public submission title did not round-trip: {body!r}")


def _reviewer_submission_titles(api_url: str, reviewer_token: str) -> set[str]:
    status, body = request(
        api_url,
        "/api/reviewer/submissions",
        reviewer_token=reviewer_token,
    )
    assert_status(status, 200, "/api/reviewer/submissions")
    if not isinstance(body, list):
        raise AssertionError(f"reviewer submissions response was not a list: {body!r}")
    return {str(item.get("title")) for item in body if isinstance(item, dict)}


def assert_live_phase3_seeded(
    api_url: str, reviewer_token: str, live_submission_title: str
) -> list[str]:
    _create_submission(api_url, live_submission_title)
    titles = _reviewer_submission_titles(api_url, reviewer_token)
    if live_submission_title not in titles:
        raise AssertionError("live Phase3 submission was not durably readable")
    return ["live-phase3-submission:created"]


def assert_demo_phase3_isolated(
    api_url: str,
    fixture_id: str,
    reviewer_token: str,
    live_submission_title: str,
    demo_submission_title: str,
) -> list[str]:
    # This must be the first request after a demo API recreation: reviewer/write
    # paths cannot rely on a catalog read to select their isolated store.
    before = _reviewer_submission_titles(api_url, reviewer_token)
    if live_submission_title in before:
        raise AssertionError("demo reviewer state included the live Phase3 submission")
    _create_submission(api_url, demo_submission_title)
    after = _reviewer_submission_titles(api_url, reviewer_token)
    if demo_submission_title not in after or live_submission_title in after:
        raise AssertionError("demo mutation was not isolated from the live Phase3 store")
    checks = assert_demo(api_url, fixture_id)
    return [*checks, "demo-phase3-submission:memory-only"]


def assert_live_phase3_restored(
    api_url: str,
    reviewer_token: str,
    live_submission_title: str,
    demo_submission_title: str,
) -> list[str]:
    titles = _reviewer_submission_titles(api_url, reviewer_token)
    if live_submission_title not in titles or demo_submission_title in titles:
        raise AssertionError("live Phase3 store changed after demo mutation")
    return ["live-phase3-submission:preserved", "demo-phase3-submission:not-persisted"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    parser.add_argument(
        "--phase",
        required=True,
        choices=(
            "postgres-empty",
            "postgres-seeded",
            "postgres-stopped",
            "postgres-recovered",
            "artifact-missing",
            "artifact-empty",
            "artifact-corrupt",
            "demo",
            "live-phase3-seeded",
            "demo-phase3-isolated",
            "live-phase3-restored",
        ),
    )
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--reviewer-token")
    parser.add_argument("--live-submission-title")
    parser.add_argument("--demo-submission-title")
    parser.add_argument("--result", required=True)
    args = parser.parse_args()

    if args.phase in {"postgres-empty", "artifact-empty"}:
        checks = assert_empty_ready(args.api_url)
    elif args.phase == "artifact-missing":
        checks = assert_unavailable(args.api_url, "uninitialized")
    elif args.phase in {"artifact-corrupt", "postgres-stopped"}:
        checks = assert_unavailable(args.api_url, "unavailable")
    elif args.phase in {"postgres-seeded", "postgres-recovered"}:
        checks = assert_fixture(args.api_url, args.fixture_id)
    elif args.phase == "demo":
        checks = assert_demo(args.api_url, args.fixture_id)
    else:
        if (
            not args.reviewer_token
            or not args.live_submission_title
            or not args.demo_submission_title
        ):
            raise AssertionError(
                "Phase3 isolation assertions require reviewer token and both run-unique titles"
            )
        if args.phase == "live-phase3-seeded":
            checks = assert_live_phase3_seeded(
                args.api_url, args.reviewer_token, args.live_submission_title
            )
        elif args.phase == "demo-phase3-isolated":
            checks = assert_demo_phase3_isolated(
                args.api_url,
                args.fixture_id,
                args.reviewer_token,
                args.live_submission_title,
                args.demo_submission_title,
            )
        else:
            checks = assert_live_phase3_restored(
                args.api_url,
                args.reviewer_token,
                args.live_submission_title,
                args.demo_submission_title,
            )

    result = Path(args.result)
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text(json.dumps({"phase": args.phase, "checks": checks}, indent=2) + "\n")


if __name__ == "__main__":
    main()
