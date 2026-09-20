# T01 real API/PostGIS harness

Run the initial smoke suites from the repository root:

```text
node scripts/run-integration.mjs --suite api
node scripts/run-integration.mjs --suite live
```

The runner generates an exact Compose project ID, dynamic loopback ports, a per-run fixture
sentinel and `tmp/integration/<run-id>/` evidence. It migrates an empty PostGIS database,
seeds the processed PostgreSQL store before starting FastAPI, proves reviewer authentication,
restarts the API and reads the same record again. The browser suite uses a production-built
web image, waits for its private localhost healthcheck, and does not intercept application API
requests.

`--keep-on-failure` retains only that generated project and writes a token-free `cleanup.env`
beside the evidence. Before its first Compose operation it also writes token-free
`recovery.json`, containing the exact project, absolute artifact/repository paths, structured
Docker label-inspection arguments and the exact `compose down --volumes --remove-orphans`
arguments. Verify each listed resource label before using that recovery command. The runner
otherwise verifies resource labels before removing its own containers, networks and volumes.
Future suites or scenarios return a clear nonzero
not-implemented result. `--assert-failure` intentionally makes the HTTP assertion fail;
`--isolation-check` runs two distinct projects with distinct fixture IDs concurrently.

## Dependency lock

`apps/api/requirements.lock` is the complete Python 3.12 constraints lock for CI and test
containers. `requirements.runtime.lock` is its production subset. When updating direct
dependencies in `pyproject.toml`, resolve all transitive packages on Python 3.12, pin them in
both applicable files, and run the API Docker build plus the ordinary checks below. The lock
also pins the setuptools build backend used by the package build.

The API package explicitly includes the JSON and GeoJSON resources loaded at runtime. Validate
an installed wheel from outside the source tree when changing package layout; a successful
import from `/app` alone can hide missing package data.

## Recorded local evidence

These checks were run from base `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34` before the T01
commit. Their generated artifacts remain locally under ignored `tmp/integration/` and CI uploads
the same directory on success or failure.

| Check | Result | Evidence |
| --- | --- | --- |
| `node scripts/run-integration.mjs --suite api` | passed; migration head `20260521_0003`, fixture persisted over restart | `2026-09-20T01-36-12-263Z-6251139d` |
| `node scripts/run-integration.mjs --suite live` | passed; production browser read fixture and authenticated reviewer store | `2026-09-20T01-45-36-336Z-4adc461d` |
| `node scripts/run-integration.mjs --suite api --assert-failure` | failed as designed with `deliberate HTTP assertion failure`; cleanup and token-free recovery metadata passed | `2026-09-20T02-02-10-763Z-a10453c1` |
| `node scripts/run-integration.mjs --suite api --isolation-check` | passed with separate generated project IDs and fixture sentinels | `2026-09-20T01-38-41-993Z-7e45c533`, `2026-09-20T01-38-42-012Z-7a126e61` |
| Python 3.12 installed-wheel probe, `ruff check .`, `mypy app`, `pytest` | passed; seed/jurisdiction resources loaded outside source tree, 60 tests passed | `tmp/t01-api-ordinary-validation-2026-09-19.txt` |

The fixture checksum was `f96e52773865398ac3dbb140b83c287e202edb6c715bba5eab6756dc1e778354`.
The local images used were PostGIS `postgis/postgis@sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5`,
Mailpit `axllent/mailpit@sha256:986b14ff7b253e62883ea19fd3112806f116e5e2f221e03f12fb81c7312ff532`,
and Playwright `mcr.microsoft.com/playwright@sha256:9bd26ad900bb5e0f4dee75839e957a89ae89c2b7ab1e76050e559790e946b948`.

On Windows, `process.kill(pid, "SIGTERM")` force-terminates Node and cannot run the
runner's JavaScript cleanup handler. A controlled probe created the exact project
`urbanization_t01_c242354d7a10`; its labelled containers and volume were verified and
then removed with that project's generated Compose env file. Use the pre-created
`recovery.json` to perform the same label-checked recovery after a forced termination;
do not treat it as a successful automatic-cleanup path.

T01 does not change application migrations or production data behavior. Rollback is removing
the harness files; generated resources are isolated and disposable.
