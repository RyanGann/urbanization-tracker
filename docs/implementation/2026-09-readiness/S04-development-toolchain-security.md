# S04 — Patch frontend development tools and retain application compatibility

Execution status: [plan.json](plan.json), entry `S04`. Added September 27, 2026 after the C04 dependency inspection.

| Field | Assignment |
| --- | --- |
| Track / gate | Security / G0 |
| Depends on | [S01](S01-frontend-dependency-update.md), [T01](T01-real-api-postgis-harness.md) |
| Review | Lead review with existing browser smoke |
| PR boundary | One development dependency and lockfile PR; no application redesign. |

Read [contracts](CONTRACTS.md), [testing instructions](TESTING.md), and [handoff rules](DISPATCH.md).

## Problem and intended result

The existing audit reports ten affected package entries, all marked development dependencies. Vite 5.4.21 and Vitest 2.1.9 remained after S01 fixed runtime libraries. Development servers and build tools still process potentially untrusted input. Select patched releases compatible with Node 22 and preserve production dependency versions.

## Code to inspect

- [Web package manifest](../../../apps/web/package.json) and [lockfile](../../../package-lock.json).
- [CI workflow](../../../.github/workflows/ci.yml), existing web unit tests, and Playwright scenarios.
- [S04 evidence](../../evidence/2026-09-27-s04-development-toolchain.md).

## Implementation steps

1. Consult maintainer advisories and record exact affected and patched versions. Distinguish audit classifications from demonstrated exploitability; the application currently uses `vitest run`, without the Vitest UI server.
2. Update Vite to the patched 6.4 line and Vitest to at least 4.1.11. Refresh affected build-tool transitive packages and deduplicate compatible Vite installations. Keep direct runtime dependency declarations and their locked versions unchanged. Explain the required major upgrades.
3. Regenerate the workspace lockfile with a working npm release in an isolated directory, without carrying old node_modules into resolution. Keep manifest and lockfile together; require reproducible `npm ci` under Node 22.
4. Run existing type checks, web unit tests, production build, development and production browser smoke, and CI's real API scenarios. Make compatibility edits only when failures require them.
5. Record advisory disposition and limitations. A comparison against known advisory ranges is not a new registry audit. Do not claim zero remaining vulnerabilities without that evidence.

## Acceptance and verification

- [ ] All production package versions and integrity values remain unchanged.
- [ ] Clean Node 22 npm ci, TypeScript, six existing web tests, and production build pass.
- [ ] Existing development, production, and real API browser smoke passes in CI.
- [ ] Codex reviews the final PR revision; address findings and merge only after green CI.
- [ ] The evidence lists versions, advisory sources, exact validation scope, and remaining limitations.

## Rollout and recovery

This changes the build and development toolchain. Revert the manifest and lockfile together if compatibility fails. Restarting an existing preview requires installing the new lockfile; a merge alone does not update the user's running process.

## Outside this PR

No production library upgrades, browser navigation, public deployment, map performance claim, or changes to real source snapshots.

## Agent handoff

> Implement S04 only on merged S01/T01. Patch the reported development-tool advisories with the smallest compatible toolchain, preserve production packages, and retain existing route/map behavior. Submit a focused PR with advisory/version and validation evidence, obtain Codex review, address findings, and merge when CI is green.
