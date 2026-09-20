# Agent dispatch and lead-review rules

Prepared September 19, 2026. This package defines implementation scope. Current assignment/completion status is recorded in [plan.json](plan.json). No deployment or real-email action is authorized by these documents alone.

## Start here

The machine-readable [plan.json](plan.json) is the source of truth for guide IDs, dependencies and status. The [index](README.md) sets gates and priority; [CONTRACTS.md](CONTRACTS.md) fixes cross-PR behavior. Each individual guide defines its PR boundary.

Immediate assignments:

1. **T01:** real API/PostGIS harness and reproducible dependencies.
2. **S01:** frontend security update, independently of T01.
3. After T01, **C01** and **P01** can proceed independently with coordination on shared test files.
4. After C01, **U00** fixes today's filter omissions and **C02** starts durable writes. After C01/P01, **P02** removes the startup bulk download.
5. Continue the performance chain and correctness chain as dependencies land. Do not wait for optional environmental expansion or 3D to deliver these improvements.

C02/C03/C06/P03/P04/P05/P07/C07/C08/D02/C09 require substantive lead review. A cheaper coding agent can implement them, but must not decide migrations, identity rules, notification semantics or geometry tradeoffs alone. Bounded routine assignments include U00, P01/P02, P06/P08/P09, U01/U02/U03 and later E04 once interfaces exist.

## PR sizing and scope

One guide equals one intended review unit with one main behavior change. Estimates are deliberately not schedule commitments: fixture/migration discoveries may justify splitting a guide. If implementation becomes several independently deployable changes or obscures the main correctness argument, split it into named sub-PRs in plan.json before expanding the diff.

Keep each PR independently testable with additive schema and feature availability states. It may depend on a prior PR without pretending the entire product is complete. Do not combine a dependency upgrade, database migration and visual redesign merely because they touch the map.

T01 establishes the runner; later guides add their scenarios. P01 establishes measurement; later guides attach before/after evidence. Never write a second competing harness, publication service, layer catalog or transaction helper.

## Branches and worktrees

Use `codex/<id>-<short-name>` branches and isolated worktrees when multiple agents actually work concurrently. All dependencies must be merged or the task must explicitly target a reviewed dependency branch/SHA. Record the base SHA in the handoff.

The current baseline is `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Re-read the actual current code and completed dependency PRs rather than assuming the September guide's line numbers remain current. Repository-relative links work on GitHub and in isolated worktrees; resolve them against the checkout assigned to the task.

Do not use the user's running preview, saved data, unrelated Postgres container or private credentials as test fixtures. Use T01's isolated project/ports/volumes. Documentation-only work does not require rerunning unrelated application tests.

## Shared-file ownership and merge order

| Shared surface | Lead coordination rule |
| --- | --- |
| models.py + Alembic revisions | One migration owner at a time; chain from current head; test upgrade from prior head |
| phase3_store.py / processed_store.py | C02 foundation first; source/review/publication callers migrate in dependency order |
| main.py / schemas.py / web api.ts / types.ts | Contract owner declares additions; avoid parallel incompatible endpoint/schema changes |
| MapPage.tsx / DevelopmentMap.tsx | S01/U00 fixes land early; P06 overlays and P08 viewport client integrate sequentially if edits overlap |
| ingestion pipeline and CLI | Source identity/coverage, spatial imports and artifact sink agree on activation prerequisites |
| test runner / CI workflow | T01 owns lifecycle; guide owners add scenarios without duplicating service setup |

Independent branches may research or prepare fixtures in parallel, but dependency readiness and shared-file ownership govern integration. Never run two agents editing the same checkout files simultaneously without explicit coordination.

Migration policy: add, backfill in bounded batches, reconcile, switch reads/writes, then consider cleanup in a separate later PR. No dropping raw artifacts/history or editing an applied migration. Prefer application rollback and active-version pointers while retaining additive schema/data. Downgrade scripts must disclose any unavoidable loss; do not casually run them on live data.

## Copyable assignment template

```text
Task: Implement <ID> from docs/implementation/2026-09-readiness.
Guide: <absolute path to the guide in your checkout>
Branch/base: codex/<id>-<name>, based on <verified dependency SHA>
Dependencies merged: <IDs and SHAs>
Scope: Only this guide's stated behavior and necessary regression tests.
Read first: CONTRACTS.md, TESTING.md, DISPATCH.md; PERFORMANCE.md for P-series.
Approved decisions: The shared contracts and the guide's defaults.
Environment: Isolated T01 stack; never mutate the working snapshot or another app's DB.
Completion: A focused diff, exact commands/results, fixture hashes, relevant visual/API
evidence, migration/recovery notes, and a list of remaining risks/unrun checks.
Escalate to lead: A contract cannot hold, identity collision, source permission ambiguity,
unsafe migration, geometry correctness change, or a need to expand into another guide.
Do not: Deploy, create paid resources, send real mail, silently weaken tests/budgets,
or declare the alpha ready merely because this PR passes.
```

Escalation means finish independent authorized work and bring a concrete conflict/proposal to the lead. Routine coding choices, naming, reversible local fixes and test reruns do not require asking the user repeatedly.

## Lead acceptance checklist

- The original failure is reproduced by a meaningful test, or the new feature has a real observable acceptance scenario.
- Application endpoints reach real PostGIS for persistence/spatial/concurrency claims. Mocked tests alone are insufficient.
- Public contracts, identity/provenance, data modes, coverage and error states agree across API/client.
- New migration/backfill is restartable, reconciled and preserves existing IDs/history; rollback avoids destroying newer writes.
- Relevant functional/performance/security checks pass, with unrun checks and external failures called out.
- No hidden source/geometry truncation, unbounded response/cache, fake location or quiet fallback masks a failure.
- The diff fits the guide; shared-file conflicts are resolved against the newest dependency code.
- User-visible changes are inspected, including narrow screen/keyboard paths when affected.
- plan.json status/PR/evidence is updated only after review. A guide is not complete merely because a draft PR exists.

Use statuses planned, in_progress, in_review, blocked, complete. Blocked entries state the concrete dependency/decision and work already finished in blocked_reason. Store implementation PR URL and evidence path when they exist; leave them null now. Evidence paths are relative to this plan directory. Re-run `node scripts/validate-readiness-plan.mjs` after changes; the [validator](../../../scripts/validate-readiness-plan.mjs) is checked into the repository.

## Release versus implementation decisions

O04 prepares the exact code-license/source-use/provider choices. Engineering can continue while those choices are pending. Unresolved redistribution/display rights block the affected public source; an unselected code license blocks promoting licensed reuse. Neither prevents isolated local tests.

O03 produces a concrete release candidate, restore proof, acceptance report and deployment commands. A later deployment decision should review those artifacts. This package does not enable ingestion, send invitations, install scheduled canaries or publish a site.

G4 environmental additions and X01's optional five-day 3D experiment follow the dependable pilot. A failed or inconclusive experiment leaves the existing application intact.

## Suggested topological order

One valid dependency order (not a promise of parallel execution):

S01 → T01 → C01 → P01 → C02 → P02 → U00 → C03 → O01 → P03 → S02 → C04 → D01 → P04 → C05 → O04 → P05 → C06 → P06 → C07 → D02 → P07 → C08 → P08 → S03 → U01 → U02 → O02 → P09 → U03 → U04 → C09 → O03 → E01 → E02 → X01 → E03 → E04

Use the index's track priorities to choose among ready tasks. Avoid a long serial queue merely because this example lists independent work in one line.
