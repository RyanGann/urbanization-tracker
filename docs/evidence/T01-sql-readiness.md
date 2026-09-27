# T01 bounded TCP SQL readiness follow-up

The clean C04 run `2026-09-27T09-04-05-163Z-4d5e63c4` on
`85f6cd4aedc54197486960a12bc05c126c3f13ec` failed before application assertions.
Retained service logs showed database startup around 09:05:41 UTC, temporary
Unix-only readiness at 09:06:04.249, initialization shutdown at 09:06:27.216,
and final TCP readiness at 09:06:37.963. The prior harness had a 60-second outer
window, a new API container per SQL attempt, a separate 60-second command cap,
and a two-second delay while requiring two successes. This measured startup
exceeded its readiness window; it was not an application assertion failure.

The replacement starts one API-context poller with an authoritative 180-second
host deadline including container startup. Monotonic host elapsed time prevents
wall-clock drift from extending that cap; the child converts the shared absolute
deadline to a monotonic budget clamped to 180 seconds. Only this command uses
immediate timeout kill escalation; interruption and owned Compose cleanup retain
the runner's existing handling. No scenario assertion timeout changed.

The poller requires an explicit single TCP hostname, rejects encoded Unix socket
hosts and host/service/port overrides, and selects one resolved TCP address while
preserving the DSN hostname for authentication/TLS. PostgreSQL documents a
two-second minimum for `connect_timeout` and separate budgets per host/address;
the single-address connection prevents multiplication of that budget.
[PostgreSQL 16 libpq connection documentation](https://www.postgresql.org/docs/16/libpq-connect.html)
Each attempt reserves two seconds for connect and two for SQL, with a 2,000ms
statement timeout bounding server query execution; no new attempt begins without
the reservation. The authoritative host deadline also fences client transport
and connection-close stalls. DNS
resolution consumes the remaining budget and is fenced by the host cutoff,
rather than claimed to have a separate resolver timeout. Two consecutive
`SELECT 1` successes separated by one second establish readiness. Transient
connection/resolver failures retry; unavailable targets fail closed. Logs contain
UTC, elapsed/budget/remaining milliseconds, attempt number and safe error
class/SQLSTATE, never DSNs, credentials or raw driver messages.

Local checks passed Ruff, mypy for 57 application files, all 429 API tests
(two upstream deprecations), 20 focused Python readiness cases and five Node
process/deadline cases. Fake clocks cover startup-budget consumption, stalled
connect/resolution, transient reset, clock drift and unavailable targets; process
tests cover a single invocation, hard timeout and interruption propagation.
No model or migration changed; the owning real proof must verify migration 0008.

Real proof and exact teardown evidence will be recorded after the clean run.
