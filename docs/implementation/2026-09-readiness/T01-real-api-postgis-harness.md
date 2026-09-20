# T01 — Run integration tests against the real API and PostGIS

Execution status: [plan.json](plan.json), entry `T01`. Guide baseline: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`. Prepared September 19, 2026.

| Field | Assignment |
| --- | --- |
| Track / gate | Foundation / G0 |
| Depends on | None; may start now |
| Review | Lead review |
| PR boundary | One harness PR; regression scenarios are added by their owning PRs. |

Read the shared [contracts](CONTRACTS.md), [testing instructions](TESTING.md) and [handoff rules](DISPATCH.md) first. New endpoints, settings, tables and runner commands below are **proposed work**, not existing capabilities.

## Problem and intended result

The existing Chromium suite intercepts the API, and many persistence tests replace database functions with mocks. Passing those suites does not demonstrate ingestion, HTTP handlers, migrations, persistence, or concurrency together.

## Code to inspect

- [apps/api/pyproject.toml](../../../apps/api/pyproject.toml)
- [apps/api/Dockerfile](../../../apps/api/Dockerfile)
- [apps/api/alembic/env.py](../../../apps/api/alembic/env.py)
- [apps/web/playwright.config.ts](../../../apps/web/playwright.config.ts)
- [.github/workflows/ci.yml](../../../.github/workflows/ci.yml)
- [Makefile](../../../Makefile)

These are inspection starting points, not a requirement to put all new code in existing large modules. Prefer a small purpose-specific module where the guide introduces a new service. Add migrations at the current Alembic head; never edit an applied migration.

## Implementation steps

1. Add a separate compose.integration.yml and a cross-platform Node runner at scripts/run-integration.mjs. The current Windows host has Node/Docker but no working Python, so run Python checks inside the test container. Start PostgreSQL 16/PostGIS 3.4, the actual FastAPI process, a production-built web preview, and a local SMTP sink. Use an isolated Compose project and volumes per run, loopback or container-only ports, explicit test credentials, and generated fixture data. Never mount the working data directory writable.

2. Set both store backends to postgres before importing the application. Run the real Alembic chain from an empty database and check PostGIS availability. Bind ports dynamically and pass the resolved API URL into the web build; do not assume the existing preview ports are available.

3. Resolve Python 3.12 runtime/dev dependencies into one checked-in, reproducible lock or constraints set used by Docker and CI. Preserve the existing pyproject as the direct dependency declaration. Fix Docker packaging/import order if necessary; prove app imports without an accidental working-directory dependency.

4. Add a separate Playwright live configuration with no route interception of application API requests. Start with health, an empty database, one fixture record read through HTTP, reviewer authentication, and persistence after API restart. Existing mocked smoke tests remain fast unit-level coverage.

5. Expose the future commands specified in TESTING.md. Store logs, test reports, traces on failure, migration revision, and fixture hashes under tmp/integration/<run-id>. Teardown only resources labelled with this runner's exact project ID.

## Acceptance and verification

- [ ] From a clean environment, one command builds, migrates, seeds, tests, restarts the API, rechecks the record, and exits nonzero on a deliberate HTTP assertion failure.
- [ ] Run two isolated test projects concurrently; their records and volumes do not cross. Verify an unrelated database/preview remains running.
- [ ] CI runs the live smoke suite with real database connections and no external city-service access. A failed migration prevents the browser suite from starting.
- [ ] Run the affected existing lint/types/tests plus the real-stack scenarios above; retain exact commands, SHA, fixture checksum and results. Do not claim an unrun check passed.
- [ ] Update API/client schemas and user-facing error states together when their contract changes; report any departure from the shared contract before merging.

## Rollout and recovery

This PR adds testing infrastructure only. It must not change current production data behavior or require a cloud account. Pin container images or record exact digests in test evidence.

## Outside this PR

Do not fix every failing business scenario here, create a general test framework, use the default developer Compose database, or change production hosting.

## Agent handoff

> Implement T01 only, after its dependencies are merged. Build the isolated real-stack test runner and only its initial smoke checks. Report the exact command and evidence that the HTTP request reached a real PostGIS-backed API. Use the acceptance checklist above as completion criteria. Return a focused diff, validation evidence, migration/rollback notes and any remaining risks. Do not deploy, send real email, refresh the working snapshot, or expand into another guide.
