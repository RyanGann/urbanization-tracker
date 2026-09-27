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

Local checks passed Ruff, mypy for 57 application files, all 429 API tests before
the final late-close/decoded-resolver guards (two upstream deprecations), then
20 focused Python readiness cases covering the final guards and five Node
process/deadline cases. Fake clocks cover startup-budget consumption, stalled
connect/resolution, transient reset, clock drift and unavailable targets; process
tests cover a single invocation, hard timeout and interruption propagation.
No model or migration changed; the owning real proof must verify migration 0008.

## Clean owning runtime proof

`node scripts/run-integration.mjs --suite api` passed on exact clean runtime SHA
`83f7d34c4cb95b6d72ae867248fda5721269bb53`, based on merged main
`8b4889d6891a646c1e95246dcf355beb8570d513`.
Run `2026-09-27T09-17-25-613Z-5f2a2e80`, project
`urbanization_t01_3e20ae446a9b`, recorded `working_tree_dirty=false`,
`outcome=passed`, `cleanup_result=removed` and no cleanup failure.
Fixture SHA256: `932eacb03655a3dee1a2838abf9ddf8d5dfa44f744482408611b61a2561bbee2`.

The single poller started at 09:18:03.010 UTC with 174,946ms remaining: its
5,054ms container startup was charged to the host's 180-second readiness budget
(Compose build/database service startup precede that budget). It produced twelve
safe transient failures while the temporary Unix-only server was ready from
09:18:02.782, through initialization shutdown at 09:18:12.343. Final TCP readiness
was 09:18:14.885. Attempts 13 and 14 succeeded at 09:18:15.223 and 09:18:16.253,
1.030 seconds apart; readiness took 13,244ms inside the poller, leaving 161,702ms.
This successful run did not reproduce the earlier slow host startup; it proves
the poller waited through actual Unix-only initialization instead of accepting
that early server. Fake clocks separately exercise exhausted/stalled budgets.

Actual migration output confirmed `20260924_0008 (head)`. The real API returned
the deterministic PostgreSQL fixture, denied unauthenticated reviewer access,
accepted the authenticated PostgreSQL-store check and retained the same fixture
after API restart. Independent exact-project Docker queries found zero
containers, zero volumes and zero networks after teardown. Service/command logs
and the manifest remain under the ignored run directory above. The following
proof-document commit changes no runtime code; final-head CI also owns all
existing scenarios and the complete API suite.
