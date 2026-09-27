from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "database_readiness", Path(__file__).parent / "integration" / "database_readiness.py"
)
assert spec and spec.loader
poller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(poller)


class FakeClock:
    def __init__(self):
        self.elapsed = 0

    def now(self):
        return self.elapsed

    def wall(self):
        return 1000 + self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds


def probe(sequence, *, startup=0, timeout=180, resolver_delay=0, resolver_fails=False):
    clock = FakeClock()
    clock.elapsed = startup
    logs = []
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query):
            assert query == "SELECT 1"
            return self

        def fetchone(self):
            return (1,)

    def connect(dsn, **kwargs):
        calls.append((clock.elapsed, kwargs))
        outcome = sequence.pop(0) if sequence else "fail"
        if outcome == "stall":
            clock.elapsed += 181
            return Connection()
        if outcome == "fail":
            raise RuntimeError("secret credential and connection URL must never be emitted")
        return Connection()

    def resolve_address(dsn):
        clock.elapsed += resolver_delay
        if resolver_fails:
            raise OSError("secret resolver details")
        return "127.0.0.1"

    ready = poller.wait_for_sql(
        "private-dsn", 1000 + timeout, connect=connect, clock=clock.now,
        wall_clock=clock.wall, sleep=clock.sleep,
        emit=lambda value, **kwargs: logs.append(json.loads(value)),
        resolve_address=resolve_address,
    )
    return ready, calls, logs


def test_one_poller_requires_two_stable_tcp_sql_successes_after_transient_failure():
    ready, calls, logs = probe(["fail", "success", "fail", "success", "success"])
    assert ready
    assert [call[0] for call in calls] == [0, 1, 2, 3, 4]
    assert logs[-1]["consecutive_successes"] == 2
    assert all(call[1]["connect_timeout"] == 2 for call in calls)
    assert all(call[1]["options"] == "-c statement_timeout=2000" for call in calls)
    assert all(call[1]["hostaddr"] == "127.0.0.1" for call in calls)
    assert "secret" not in json.dumps(logs)


def test_container_startup_consumes_host_budget_and_unavailable_database_fails():
    ready, calls, logs = probe([], startup=170)
    assert not ready
    assert calls[-1][0] <= 176
    assert logs[0]["budget_ms"] == 10000
    assert logs[-1]["status"] == "timeout"


@pytest.mark.parametrize("startup", [177, 180, 190])
def test_insufficient_remaining_libpq_budget_starts_no_attempt(startup):
    ready, calls, _ = probe(["success", "success"], startup=startup)
    assert not ready and not calls


def test_stalled_connection_never_produces_readiness():
    ready, calls, logs = probe(["stall"])
    assert not ready and len(calls) == 1
    assert logs[-1]["status"] == "timeout"


def test_host_child_wall_clock_drift_cannot_extend_child_budget():
    ready, _, logs = probe([], timeout=1000)
    assert not ready
    assert logs[0]["budget_ms"] == 180000


def test_resolution_consumes_budget_before_connect():
    ready, calls, logs = probe(["success"], resolver_delay=178)
    assert not ready and not calls
    assert logs[-1]["status"] == "timeout"


def test_transient_resolver_error_is_safe_retry_not_configuration_refusal():
    ready, calls, logs = probe([], timeout=6, resolver_fails=True)
    assert not ready and not calls
    assert any(row["status"] == "retry" for row in logs)
    assert "secret" not in json.dumps(logs)


@pytest.mark.parametrize("url", [
    "postgresql:///integration", "postgresql://user:secret@/integration",
    "postgresql://db/integration?host=/tmp", "postgresql://db/integration?service=local",
    "postgresql://%2Fvar%2Frun%2Fpostgresql/integration",
    "postgresql://db,other/integration", "postgresql://db%2Cother/integration",
    "postgresql://db/integration?port=5432,5433",
])
def test_unix_socket_or_service_override_cannot_signal_tcp_readiness(url):
    with pytest.raises(ValueError):
        poller.tcp_dsn(url)


def test_api_driver_url_becomes_tcp_libpq_url():
    assert poller.tcp_dsn("postgresql+psycopg://u:p@db:5432/integration") == (
        "postgresql://u:p@db:5432/integration"
    )
