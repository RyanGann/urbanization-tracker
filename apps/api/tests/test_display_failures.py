import pytest
from sqlalchemy.exc import DBAPIError

from app.ingestion.display_builder import _output_digest, _retryable_database_error


class DriverError(RuntimeError):
    sqlstate: str | None = None
    pgcode: str | None = None


@pytest.mark.parametrize("state,retryable", [
    ("40001", True), ("40P01", True), ("55P03", True), ("57014", True),
    ("08006", True), ("53200", True), ("57P01", True), ("57P03", True),
    ("58030", True), ("58000", True),
    ("40000", True), ("40002", True), ("40003", True),
    ("57000", True), ("57001", True),
    ("54000", True), ("54001", True), ("54011", True), ("72000", True),
    ("F0000", True), ("F0001", True), ("XX001", True), ("XX002", True),
    ("22012", False), ("XX000", False), (None, False),
])
def test_operational_sql_failures_do_not_become_geometry_verdicts(
    state: str | None, retryable: bool,
) -> None:
    original = DriverError("synthetic driver error")
    original.sqlstate = state
    error = DBAPIError(None, None, original)
    assert _retryable_database_error(error) is retryable


def test_invalidated_connection_is_retryable_without_sqlstate() -> None:
    error = DBAPIError(None, None, RuntimeError("synthetic disconnect"),
                       connection_invalidated=True)
    assert _retryable_database_error(error)


def test_legacy_driver_pgcode_is_recognized() -> None:
    original = DriverError("synthetic legacy driver error")
    original.pgcode = "57014"
    assert _retryable_database_error(DBAPIError(None, None, original))


def test_application_error_is_not_a_retryable_database_failure() -> None:
    assert not _retryable_database_error(RuntimeError("application failure"))


@pytest.mark.parametrize("field,value", [
    ("source_holes", 2), ("display_holes", 2), ("source_components", 2),
    ("display_components", 2), ("status", "collapsed"), ("collapsed", True),
])
def test_output_digest_authenticates_topology_and_status(field: str, value: object) -> None:
    result = {
        "status": "built", "collapsed": False, "error_code": None,
        "source_holes": 1, "display_holes": 1,
        "source_components": 1, "display_components": 1,
        "simplified_geometry_sha256": "a" * 64,
    }
    assert _output_digest(result, ["b" * 64]) != _output_digest(
        {**result, field: value}, ["b" * 64],
    )
