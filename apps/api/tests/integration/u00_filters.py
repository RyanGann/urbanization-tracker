from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

EXPECTED_IDS = {
    "u00-completed-development",
    "u00-proposed-submission",
    "u00-published-submission",
}


def request(api_url: str, path: str) -> tuple[int, dict[str, object]]:
    with urlopen(Request(f"{api_url}{path}", method="GET"), timeout=20) as response:  # noqa: S310
        return response.status, json.loads(response.read())


def request_error(api_url: str, path: str) -> tuple[int, dict[str, object]]:
    try:
        request(api_url, path)
    except HTTPError as error:
        return error.code, json.loads(error.read())
    raise AssertionError(f"expected HTTP error for {path}")


def ids_from_list(body: dict[str, object]) -> set[str]:
    return {str(record["public_id"]) for record in body["records"]}  # type: ignore[index]


def ids_from_geojson(body: dict[str, object]) -> set[str]:
    return {str(feature["id"]) for feature in body["features"]}  # type: ignore[index]


def filtered_path(path: str, **filters: list[str]) -> str:
    query = urlencode([(key, value) for key, values in filters.items() for value in values])
    return f"{path}?{query}" if query else path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()

    list_path = "/api/development-records"
    geojson_path = "/api/map/development-records.geojson"
    checks: list[str] = []

    list_status, list_body = request(args.api_url, list_path)
    geojson_status, geojson_body = request(args.api_url, geojson_path)
    assert list_status == geojson_status == 200
    assert ids_from_list(list_body) == EXPECTED_IDS
    assert ids_from_geojson(geojson_body) == EXPECTED_IDS
    checks.append("default:list-geojson-parity")

    completed_query = {"status": ["completed"]}
    list_status, list_body = request(args.api_url, filtered_path(list_path, **completed_query))
    geojson_status, geojson_body = request(
        args.api_url, filtered_path(geojson_path, **completed_query)
    )
    assert list_status == geojson_status == 200
    assert ids_from_list(list_body) == {"u00-completed-development"}
    assert ids_from_geojson(geojson_body) == {"u00-completed-development"}
    checks.append("subset:completed:list-geojson-parity")

    submission_query = {"development_type": ["public_submission"]}
    list_status, list_body = request(args.api_url, filtered_path(list_path, **submission_query))
    geojson_status, geojson_body = request(
        args.api_url, filtered_path(geojson_path, **submission_query)
    )
    assert list_status == geojson_status == 200
    assert ids_from_list(list_body) == {
        "u00-proposed-submission",
        "u00-published-submission",
    }
    assert ids_from_geojson(geojson_body) == {
        "u00-proposed-submission",
        "u00-published-submission",
    }
    checks.append("subset:public-submission:list-geojson-parity")

    list_status, list_body = request(args.api_url, filtered_path(list_path, status=["none"]))
    geojson_status, geojson_body = request(
        args.api_url, filtered_path(geojson_path, status=["none"])
    )
    assert list_status == geojson_status == 200
    assert ids_from_list(list_body) == ids_from_geojson(geojson_body) == set()
    checks.append("none:zero-list-geojson")

    for field in ("confidence", "flag"):
        query = {field: ["none"]}
        list_status, list_body = request(args.api_url, filtered_path(list_path, **query))
        geojson_status, geojson_body = request(args.api_url, filtered_path(geojson_path, **query))
        assert list_status == geojson_status == 200
        assert ids_from_list(list_body) == ids_from_geojson(geojson_body) == set()
        checks.append(f"none:{field}-zero-list-geojson")

    mixed_status, mixed_body = request_error(
        args.api_url,
        filtered_path(list_path, status=["none", "completed"]),
    )
    assert mixed_status == 422
    assert mixed_body["detail"]["code"] == "invalid_filter"  # type: ignore[index]
    checks.append("invalid:mixed-none-422")

    unknown_status, unknown_body = request_error(
        args.api_url,
        filtered_path(geojson_path, confidence=["unknown"]),
    )
    assert unknown_status == 422
    assert unknown_body["detail"]["code"] == "invalid_filter"  # type: ignore[index]
    checks.append("invalid:unknown-422")

    Path(args.result).write_text(json.dumps({"checks": checks}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
