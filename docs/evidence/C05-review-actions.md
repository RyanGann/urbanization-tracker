# C05 local review handoff — October 15, 2026

Base: `03a9e1a16d50b3b083c1086488484748349129d7` (merged PR39). Implementation commit: `7f31f9112cf729ace2abe97454b918930d16dc2a`. Remote main was verified with `git ls-remote origin refs/heads/main` and fetched before editing. Work is isolated on `codex/c05-review-actions-20261015` in `C:\Users\Ryan\Documents\Codex\2026-10-14\task\urban-c05`. The original `codex/readiness-execution` checkout and its six modified files were preserved. No repository/ancestor `AGENTS.md` or applicable `.agents/skills` guidance was present.

## Result and review boundary

- One C05 adapter resolves operational candidates and actual processed staged IDs. PostgreSQL decisions/imports and consistent queue/export reads use the existing C02 lock/session. ArcGIS audit rows have no allowed actions and return `409 review_not_actionable`; unknown IDs return 404.
- Manual pending/needs-info candidates can request information, reject, or approve with a verified location and current revision. Approved/rejected/published revisions are terminal. Stale or missing live tokens return `409 review_revision_conflict` without changing data. Submission aliases use the same decision path.
- Actor, time, notes, content/state revisions and append-only events persist together. Omitted notes retain the previous reason. Legacy notes retain an explicit baseline with unknown actor/time when necessary. Current shared-token requests record actor `reviewer`; this does not identify an individual human.
- Authenticated exports carry notes and history. Imports validate a legal continuation with the current target revision, retain the existing history prefix, report missing/conflicting IDs and refuse to overwrite newer decisions. Exact unchanged imports are no-ops. Restoring a newer snapshot into a copied older candidate requires an explicit `expected_revision` for that target and the same content revision; this is not a content/identity merge tool.
- The UI shows provenance, revision, policy, saved notes and history. A stale action preserves the draft, reloads the state, shows the changed revision/status/notes and requires acknowledgement before another manual action. A failed reload keeps actions blocked. No action is automatically replayed.
- Existing first-publication behavior is retained. Changed published content and reason-bearing retraction remain fenced for C06. Rejecting a newer candidate never removes an older public snapshot/version. This does not implement C06 publication events, versioned updates or retraction.

## Validation

Checks use Docker on this Windows host: Python 3.12 with the locked requirements and the existing Playwright/Node 22 image. Check containers are limited to two CPUs/2 GiB; browser/Vitest workers are one. T01 runs use unique projects, private databases/volumes, dynamic loopback ports, ingestion/delivery disabled and synthetic contacts/tokens. `COMPOSE_PARALLEL_LIMIT=1` serializes Compose startup. `INTEGRATION_ARTIFACT_ROOT=G:\CodexArtifacts\urban-c05` stores the real-stack reports on G:.

Commands from the worktree (API commands execute in `/app` with `PYTHONPATH=/app`):

| Command | Result |
| --- | --- |
| `ruff check .` | Passed |
| `mypy app` | Passed, 63 source files |
| `python -m pytest -o addopts='' -q` | 498 passed; two existing FastAPI/Starlette deprecation warnings |
| `npm --workspace apps/web run typecheck` | Passed |
| `npm --workspace apps/web run test -- --maxWorkers=1` | 6 passed |
| `npm --workspace apps/web run build` | Passed; existing large-chunk warning remains |
| `npm --workspace apps/web run e2e -- --workers=1` | 4 passed, 2 opt-in scenarios skipped |
| `npm --workspace apps/web run e2e:production -- --workers=1` | 1 passed |
| `node --test scripts/database-readiness.test.mjs scripts/performance/integration.test.mjs` | 7 passed |
| `node scripts/run-integration.mjs --suite live --scenario c05-review-actions` | Passed, including 1 real API Chromium test; exact run below |
| `node scripts/run-integration.mjs --suite api --scenario c04-agenda-revisions` | Passed, all owning assertions; exact run below |
| `node scripts/validate-readiness-plan.mjs` and `git diff --check` | Passed |

C05's scenario forces two independent HTTP transactions to queue behind the documented advisory lock and requires exactly one 200 and one 409. It checks actual normalized staged ID `stage-hsv-subdivision-905-a02cd491564e8bc0`, both readers' final state, submission aliases, successful manual approval, history round-trip/restore/conflicts, retained older publication/version, protected reads/writes, public privacy and exact review/public state after restart. The browser uses actual application routes without interception and covers read-only controls, stale recovery, preserved draft, keyboard acknowledgement, durable history and a 390px screen without horizontal overflow.

Synthetic C05 fixture SHA-256: `9984bf64de9c944b9617591b930200453ff9c9d1c8ffd7d44093fb8b574e08d1`. Baseline T01 fixture SHA-256: `932eacb03655a3dee1a2838abf9ddf8d5dfa44f744482408611b61a2561bbee2`.

Final C05 run: `2026-10-15T00-56-29-612Z-bd9ac114`, project `urbanization_t01_b1d798bd6151`. Manifest reports `passed`, `cleanup_result=removed`. Result SHA-256: `569b66bd028bdda33715d94dad2ffa2582654a881888a125b5b36776e38d842b`. Reports, redacted logs, JUnit and visually inspected desktop/narrow screenshots are under `G:\CodexArtifacts\urban-c05\2026-10-15T00-56-29-612Z-bd9ac114`. The run began at the base SHA with a dirty worktree; that exact application/test source was committed unchanged as `7f31f91` during the run. Unit/lint/type logs are retained in the worktree's `tmp/c05-validation` directory.

Final C04 run: `2026-10-15T01-02-00-870Z-563065b5`, project `urbanization_t01_653c0964ead2`, application SHA `7f31f9112cf729ace2abe97454b918930d16dc2a` with the reviewed C04 fixture/assertion updates. Manifest reports `passed`, `cleanup_result=removed`. Result SHA-256: `5ba08a5d72247bdcc07901702bf56c2b8bcbf4fede4c3ecee7f13e54fece7fbe`. Its result, redacted commands/service logs and manifest are under `G:\CodexArtifacts\urban-c05\2026-10-15T01-02-00-870Z-563065b5`. Application source is unchanged from the completed C05 run.

Earlier diagnostic attempts are retained separately: a point/polygon fixture mismatch, the harness's old one-record smoke assumption, an ambiguous browser text locator, a mistaken same-origin browser test request, and a fixture extension made while an earlier attempt was running. One passing browser/API attempt lost its tool session before runner finalization; its exact resources were recovered and removed before the complete final rerun above. The first C04 regression also found its older repeated-approval expectation (200); it now explicitly requires C05's terminal-revision 409 and unchanged decision/history/publication. Those incomplete/failed attempts are not acceptance evidence. No remote CI claim is made.

C04's ownership fixtures also now clear `location_required` when injecting their verified geometry/provenance, matching its earlier successful manual-location fixture. The C05 policy correctly refuses approval while that flag remains true. These fixture updates retain the original processed/mixed ownership and publication-conflict assertions.

Independent final diff review checked transaction ownership, both submission entry points, terminal transitions, error envelopes, public/private separation, history-prefix validation, legacy notes, UI draft/reload behavior and the C06 boundary. It found and corrected inconsistent export reads, unavailable-approval metadata, failed-reload acknowledgement and safe dependency-error handling before the final validation. No sub-agents were used.

Not run: upstream/network source canaries, performance benchmarks, remote CI, the separate opt-in C01/P03 browser scenarios, C06 or release/restore rehearsals. The two default-browser skips are those opt-in scenarios, not C05. No acceptance result is inferred for them. No local environment blocker remains after using the existing Docker context and locked container runtimes instead of the host's Node 20/incomplete Python environment.

## Storage, recovery and tomorrow

No Alembic migration is needed: new submission events use the existing generic durable collection table (`review_decision_events`); agenda events retain their existing collection. Schema head remains `20260927_0009`. Legacy revisionless submissions expose revision 0 and receive revision 1 on their first C05 decision; newly created submissions start at 1. Artifact mode remains local single-writer and does not acquire PostgreSQL's cross-file atomicity. Explicit demo seed rows remain session-only.

Headroom was checked before and after: C: about 30.18 → 29.15 GiB free, G: about 114.85 → 111.19 GiB free. Complete T01 runs removed their own labelled resources; the interrupted run was recovered with its exact project ID. The unrelated project database remained running. C05 check containers are removed after final checks; newly created dependency/build caches are retained.

Rollback retains the additive JSON fields/events. Reverting to the old application can bypass C05 concurrency rules, so do not resume reviewer writes with an older API/client. No schema downgrade, cache deletion, other-project data change, push, merge, deployment, production activation, paid resource or credential/security change was performed.

Next session: review this local C05 change, then scope C06's canonical publication/events/versioned-update/retraction transaction. Public activation and source redistribution/display rights, provider choices and privacy/release decisions remain deferred for Ryan. No new decision is required to inspect or test this local branch.
