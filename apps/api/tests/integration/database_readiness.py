"""One API-context TCP SQL poller; emits no connection URLs or driver messages."""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from datetime import UTC, datetime
from urllib.parse import unquote


def tcp_dsn(value):
    from sqlalchemy.engine import make_url

    url = make_url(value)
    host = unquote(url.host or "")
    if not host or any(character in host for character in ("/", "\\", ",")) or any(
        key in url.query for key in ("host", "hostaddr", "service", "port")
    ):
        raise ValueError("explicit_tcp_host_required")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def resolve_tcp_address(dsn):
    from sqlalchemy.engine import make_url

    url = make_url(dsn)
    addresses = socket.getaddrinfo(unquote(url.host or ""), url.port or 5432,
                                   type=socket.SOCK_STREAM)
    if not addresses:
        raise OSError("tcp_address_unavailable")
    return addresses[0][4][0]


def wait_for_sql(dsn, deadline_epoch, *, connect, clock=time.monotonic,
                 wall_clock=time.time, sleep=time.sleep, emit=print, resolve_address=None):
    started = clock()
    budget = min(180, max(0, deadline_epoch - wall_clock()))
    deadline = started + budget
    successes = 0
    attempts = 0

    def report(status, error=None):
        payload = {"probe": "database_tcp_sql", "status": status, "attempt": attempts,
                   "utc": datetime.fromtimestamp(wall_clock(), UTC).isoformat(),
                   "elapsed_ms": round((clock() - started) * 1000),
                   "remaining_ms": max(0, round((deadline - clock()) * 1000)),
                   "budget_ms": round(budget * 1000), "consecutive_successes": successes}
        if error is not None:
            payload["error_type"] = type(error).__name__
            state = getattr(error, "sqlstate", None)
            if isinstance(state, str) and len(state) == 5 and state.isalnum():
                payload["sqlstate"] = state
        emit(json.dumps(payload), flush=True)

    report("started")
    # libpq's integer connect_timeout has a two-second minimum. Reserve another
    # two seconds for the query; don't begin an attempt with less than that.
    while deadline - clock() >= 4:
        attempts += 1
        try:
            target = {"hostaddr": resolve_address(dsn)} if resolve_address else {}
            if deadline - clock() < 4:
                break
            with connect(dsn, connect_timeout=2, autocommit=True,
                         options="-c statement_timeout=2000", **target) as connection:
                if deadline - clock() < 2:
                    break
                value = connection.execute("SELECT 1").fetchone()
                if clock() >= deadline:
                    break
                if value != (1,):
                    raise ValueError("unexpected_sql_result")
            if clock() >= deadline:
                break
            successes += 1
            report("success")
            if successes == 2:
                report("ready")
                return True
        except Exception as error:
            successes = 0
            report("retry", error)
        sleep(min(1, max(0, deadline - clock())))
    report("timeout")
    return False


if __name__ == "__main__":
    import psycopg

    try:
        dsn = tcp_dsn(os.environ["DATABASE_URL"])
        ready = wait_for_sql(dsn, float(sys.argv[1]), connect=psycopg.connect,
                             resolve_address=resolve_tcp_address)
    except Exception as error:
        print(json.dumps({"probe": "database_tcp_sql", "status": "configuration_refused",
                          "error_type": type(error).__name__}), flush=True)
        ready = False
    sys.exit(0 if ready else 1)
