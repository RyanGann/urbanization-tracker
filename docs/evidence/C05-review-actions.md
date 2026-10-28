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

## Recovery and revalidation - October 28, 2026

Recovered the exact clean local head `f0936c4f63b0d705ac74f823ac517881ddd50e5d`, including implementation `7f31f9112cf729ace2abe97454b918930d16dc2a`. GitHub and a fresh fetch independently confirm current main is still the original base `03a9e1a16d50b3b083c1086488484748349129d7`; there is no rebase or application reconciliation to perform. The original worktree, ignored historical logs, other branches and unrelated local changes were left in place. Initial sandbox Git/Docker failures were environment restrictions; elevated read-only diagnostics confirmed the original worktree is healthy and clean and the local daemon is available.

Recovery artifacts are under `C:\Users\Ryan\Documents\Codex\2026-10-27\task-4`: complete-history `c05-preserved.bundle` (SHA-256 `0889ac05dbe5314e287a4068e2749dff8205d7522b094bdcb9b44aa3dbe96104`) and exact two-commit `c05-preserved.patch` (`f1a238a590e3847ad62a8140d8b5411122bdeb3efa59f2d6dbb0d261b724437f`). Git verifies the bundle is self-contained. Original index/worktree patches are empty; both hash to `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. Historical unit logs were copied to `c05-historical-unit-logs`; the original G: acceptance result hashes above were independently reverified.

Validation used the isolated `urban-c05-validated` checkout. No application code or dependency lock differs from the recovered milestone. The preserved development-check image matches every pinned development requirement; Python is 3.12.14. The existing Playwright image actually reports Node 24.15.0, which meets the declared Node >=22 requirement. Networking was disabled for unit/build/browser checks. Current logs are in `tmp/c05-recovery-validation`.

| Current command | October 28 result |
| --- | --- |
| `ruff check .`, `mypy app` | Passed; 63 application files |
| `python -m pytest -o addopts='' -q` | 498 passed, two existing deprecation warnings |
| `npm --workspace apps/web run typecheck` | Passed |
| `npm --workspace apps/web run test -- --maxWorkers=1` | 6 passed |
| `npm --workspace apps/web run build` | Passed; existing large-chunk warning |
| `npm --workspace apps/web run e2e -- --workers=1` | 4 passed, 2 documented opt-in skips |
| `npm --workspace apps/web run e2e:production -- --workers=1` | 1 passed |
| `node --test scripts/database-readiness.test.mjs scripts/performance/integration.test.mjs apps/web/e2e/performance/metrics.test.mjs` | 16 passed |
| `node scripts/validate-readiness-plan.mjs`, `git diff --check` | Passed |

The ordinary integration rebuild began fetching dependencies rather than reusing every cached layer and was interrupted before acceptance. Run `2026-10-28T03-54-10-283Z-cda49659`, project `urbanization_t01_df95baaa2327`, has no acceptance manifest and left zero labelled resources. Subsequent real-stack runs use a clearly labelled temporary copy of the ordinary runner, `tmp/run-integration-offline.mjs`, with `tmp/offline.compose.yml`. Only imports/runner location, the Compose path and manifest description change; all owning assertions, migrations, lifecycle, restart and cleanup logic remain intact. Temporary Dockerfiles copy the current checked-out app/migrations/browser sources onto the preserved locked-dependency images and rebuild the web assets without package installation. Build steps have `network: none`; API/database/web/browser services are limited to two CPUs/two GiB. These local adaptations are retained under `tmp` and are not production Dockerfile or CI changes.

Commands use `COMPOSE_PARALLEL_LIMIT=1` and `INTEGRATION_ARTIFACT_ROOT=<checkout>/tmp/c05-integration`:

- `node tmp/run-integration-offline.mjs --suite live --scenario c05-review-actions`: passed on clean `f0936c4`, run `2026-10-28T03-58-46-620Z-eddfdb49`, project `urbanization_t01_59d2d047a09c`, result SHA-256 `3380d7d756267dec3e6a2ba22f71e543176e77a58a1ea972f269bde728e38ba4`. Real API race returned 200/409; restart/history/restore/privacy/publication assertions and one real Chromium test passed. Desktop conflict and 390px screenshots were visually inspected.
- `node tmp/run-integration-offline.mjs --suite api --scenario c04-agenda-revisions`: passed on clean `f0936c4`, run `2026-10-28T04-02-37-835Z-23ae45fc`, project `urbanization_t01_abea652c26d6`. All 25 owning boolean assertions are true; result SHA-256 is still `5ba08a5d72247bdcc07901702bf56c2b8bcbf4fede4c3ecee7f13e54fece7fbe`.
- `node tmp/run-integration-offline.mjs --suite api --scenario input-limits`: passed on clean `b2928217f282eb5afa02428c4a3a3c4b59875f27`, run `2026-10-28T04-06-53-126Z-27cdd7fb`, project `urbanization_t01_e53f1a86ef44`. All six S02 groups and quota persistence after restart pass; each two-worker quota admits 10/rejects 10. This follow-up changes only the existing fixture: supply current revision tokens, require the existing `location_required` error, assert per-item import conflicts preserve revision/status/notes/history, and retain successful located publication and privacy checks.

Each complete run reports `cleanup_result=removed`; independent exact project-label queries confirm zero containers, volumes and networks. Earlier S02 run `2026-10-28T04-03-50-334Z-13c680c4` reproduced the old fixture's top-level import-409 assumption. Run `2026-10-28T04-05-18-775Z-c59b86fd` exposed an overly strict new assertion for `review_not_actionable`; S02's existing geometry fence correctly returns `location_required`. Both failures and successful final proof are retained separately and their exact resources are absent. Initial API tests lacked the repository-root blueprint mount (496 passed/two environment failures); the full correctly mounted rerun passed all 498. Two host metrics failures were loopback-access restrictions; all 16 passed in the network-isolated container.

The baseline fixture's raw SHA-256 is now `f96e52773865398ac3dbb140b83c287e202edb6c715bba5eab6756dc1e778354` because this recovery checkout uses Git's LF bytes. Its parsed JSON and CRLF-normalized original bytes are identical to the preserved fixture; the C05 canonical synthetic fixture hash remains `9984bf64de9c944b9617591b930200453ff9c9d1c8ffd7d44093fb8b574e08d1`. Schema head remains `20260927_0009`; no migration is added.

The C04 prerequisite manifest entry is reconciled to complete: PR37 is merged, and exact source-head CI run `36311582338` is successful. C05 remains in review until the new PR, exact-head CI and supported Codex review are complete. No C06 work is started.

Before any remote mutation, repository hooks and workflows were inspected: the CI workflow has no deployment command and only main pushes trigger push CI. `render.yaml` links all services to main with `autoDeployTrigger: checksPass`; API pre-deploy runs Alembic and the layer-catalog upgrade. Automatic approval review rejected an early feature push while integration checks were still running; it did not execute. Any retry must use the completed local acceptance evidence above. Render management metadata could not be read without a confirmed workspace; no service endpoint or deployment request was made. Render documents that `[skip render]` in a PR title suppresses previews and in a Git commit message suppresses auto-deploys. Preserve this marker on the PR and any eventual merge commit; changing live deployment/ingestion/alerts/providers remains separately gated. See [service previews](https://render.com/docs/service-previews) and [auto-deploy skipping](https://render.com/docs/deploys#skipping-an-auto-deploy).

Both unchanged API locks still pin `certifi==2026.7.22`, affected by [GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2). [Python's incident guidance](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576) recommends certifi 2026.10.19 or later and patched packaging/runtime trust stores. The offline/private synthetic tests establish C05 behavior, not external TLS or release safety. A separate dependency/runtime remediation and release validation are required before live release; no unrelated upgrade was folded into C05. Upstream canaries, performance benchmarks, C01/P03 opt-in browser scenarios, release/restore rehearsals and live requests were not run. Remote CI and review results must be recorded separately after the PR exists.

After all applicable local checks passed, the single evidence-based push retry succeeded. [Draft PR40](https://github.com/RyanGann/urbanization-tracker/pull/40) contains the preserved milestone plus the focused S02 fixture correction and recovery evidence. Its title includes `[skip render]`; CI and the established Codex integration must review the exact final head before merge. No deployment or activation was requested. Final S02 result SHA-256 is `727267644500126686ee647a63ca374306770a0f13ae9c6b8bc8960dd168f1b0`.

CI run `40630789675` on `8c80f00` passed readiness, API lint/types/all 498 tests and web types/all six tests/build, then failed installing browsers: the hosted `ubuntu-latest` label now resolves to Ubuntu 26.04.1, unsupported by locked Playwright 1.60.0. All subsequent browser/integration steps were skipped. Pin the CI runner to supported Ubuntu 24.04, matching the existing Noble browser image; no dependency or test is removed or upgraded. The full workflow must rerun. The superseded initial run had already completed when cancellation was requested; no successful result is inferred. GitHub deployment metadata for the guarded PR/head returned an empty list. CI's unchanged npm lock also reports four audit findings (two moderate/two high); these were not auto-fixed or independently triaged in C05 and remain release follow-up alongside certifi.
