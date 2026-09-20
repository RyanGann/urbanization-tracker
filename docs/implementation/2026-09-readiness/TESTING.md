# Real API, upstream and acceptance testing

Prepared September 19, 2026. **T01 owns the harness; each guide owns its regression scenarios. Consult [plan.json](plan.json) and the owning PR's evidence before assuming a command or scenario is available.** The September review already ran 60 backend tests, four web unit tests and three mocked Chromium smoke tests; those results do not establish the new integration checks.

## Test layers and when they run

| Layer | Actual dependencies | When / purpose |
| --- | --- | --- |
| Existing unit and mocked UI tests | Local fixtures, controlled mocks | Every relevant PR; fast logic checks |
| Store/API integration | Real PostgreSQL/PostGIS, Alembic, FastAPI over HTTP | Every backend/data PR; state, transactions, schema and errors |
| Live browser workflows | Built web app + real API/database; local deterministic basemap | Every affected UI PR; no intercepting application API routes |
| Connector contract fixtures | A local HTTP server emulating ArcGIS/PDF source responses | Every ingestion PR; paging, failures, malformed data and replay |
| Upstream canaries | Actual official service metadata and small bounded queries | Explicit opt-in/manual or a deliberately configured schedule; detect source drift separately |
| Performance | Real stack plus generated large fixtures | Structural budgets in PR CI; timing on a recorded reference profile |
| Recovery/release rehearsal | Copied dataset, isolated DB/object store/mail sink | O03 and material migration changes |

A live API test means a running service connected to a real database, not an in-process TestClient with storage monkeypatched. Fixtures may replace **external source services** and SMTP, but not the application endpoints being tested. No production test-only HTTP routes should be added for seeding; seed through a test CLI/import mechanism before the server starts or through normal authorized API operations.

Use Playwright's [web-server lifecycle support](https://playwright.dev/docs/test-webserver) or the runner's equivalent health-wait/teardown logic. PostgreSQL's [transaction locks](https://www.postgresql.org/docs/16/explicit-locking.html) and SQLAlchemy's [session transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html) define the concurrency behavior the tests must verify.

## Harness and proposed commands — owned by T01

Add `compose.integration.yml`, `scripts/run-integration.mjs`, separate live/performance Playwright configs and deterministic fixture generators. Expose these commands from the repository root on Windows and Linux:

```text
node scripts/run-integration.mjs --suite api
node scripts/run-integration.mjs --suite live
node scripts/run-integration.mjs --suite live --scenario review-replay
node scripts/run-integration.mjs --suite concurrency
node scripts/run-integration.mjs --suite recovery
node scripts/run-integration.mjs --suite performance --profile desktop
node scripts/run-integration.mjs --suite performance --profile mobile
node scripts/run-integration.mjs --suite upstream --allow-network --max-requests 20
```

The runner must reject unknown suites/scenarios and unsupported flag combinations rather than silently running a smaller test. T01 implements api/live and the dispatch structure; later PRs add their owned suites/scenarios. Until a suite exists, print a clear nonzero 'not implemented' result. Existing `make test-performance` is not the new benchmark and must not be described as equivalent.

Default runner behavior: create an exact unique Compose project ID, isolated volumes and generated data, build images, apply migrations, seed, health-wait, test, retain reports, teardown only this run's labelled resources. Optional `--keep-on-failure` prints exact cleanup commands and labels. Do not interpolate untrusted project names into shell command strings.

Use Node/Docker on this Windows host; Python checks run in containers. A pre-existing unrelated Postgres container used host port 5432 during review, and the user's preview uses 5173/8000. Choose dynamic loopback ports or container-only networking. Never use bare default `docker compose down -v`, terminate arbitrary processes, or mount the working `data` directory writable.

Set DATA_MODE=live, both store backends=postgres and test database URL before application import, because settings/engine are cached. Set hosted ingestion false and delivery false by default. Enable mail only in a specific scenario with the local sink hostname and credentials. Block public SMTP access from the test network. Use an S3-compatible emulator for artifact tests.

Produce `tmp/integration/<run-id>/` with redacted service logs, JUnit/JSON reports, migration revision, fixture hashes, Playwright traces on failure, timing/payload results and exact reproduction command. Never retain bearer tokens, raw email tokens or private user payloads in shared artifacts.

## Required scenario matrix

| Scenario / owning PR | Setup and action | Required observation |
| --- | --- | --- |
| empty-live / C01 | Initialized empty store; missing/corrupt artifact; stopped DB; explicit demo | Zero real records vs 503 vs labelled demo remain distinct |
| filters / U00 | Completed, proposed and public-submission records; all/subset/none | Default includes eligible records; none never broadens |
| concurrent-create / C02 | Barrier starts two independent HTTP clients/connections | Both submissions/watches survive; injected mid-write failure rolls back |
| source-identity / C03 | Same ID with renamed/status-changed feature; partial/empty refresh | Stable public URL/first discovery; no inferred deletion from partial data |
| source-pages / D01 | >2 pages; absent transfer flag; repeated page; 429; bad geometry | Reconciled scoped coverage or explicit incomplete outcome |
| review-replay / C04 | Reject, ingest unchanged agenda, ingest changed revision | Decision persists for unchanged content; new pending revision preserves history |
| review-conflict / C05 | Two decisions with same expected_revision; actual processed staged ID | One succeeds/one 409; processed read-only returns explanatory 409 |
| publication / C06 | Create/update/retract through normal paths; retry/last_checked-only | Atomic canonical row/event/version; no duplicate/no-op event |
| input-limits / S02 | Invalid geometry/URL/body, concurrent quota requests | 413/422/429, no fabricated location or private-data leak |
| future-watch / C07 | Activate watch, publish later matching/nonmatching records, restart/retry | One logical outbox item per matching event; exact spatial semantics |
| subscription / S03 | Exact generated web link, GET scan, POST confirm/opt-out | Correct split-origin navigation; GET nonmutating; verified state controls mail |
| delivery / C08 | Two workers, timeout, transient/permanent rejection, crashed lease | Safe claim/retry/suppression and documented SMTP duplicate window |
| layer-import / P03–P04 | Replay/fail import, change derivative config, switch active version | Original geometry unchanged; no partial activation; old version remains usable |
| tile-contract / P05 | Decode dense/empty/border tiles; conditional/compressed responses | Correct source-layer/geometry/cache headers; errors never become empty success |
| live-map / P06–P08 | Pan/filter/select/toggle with delayed out-of-order responses | No legacy bulk fetch; latest scope wins; sources/DOM remain bounded |
| map-state / U01–U02 | Shared URL, back/forward, local search, failed basemap | Restorable truthful state, keyboard search, attribution and recovery |
| participation / U03 | Distinct watch/submission geometry; explicit unknown | Independent correct payloads and reviewable unknown location |
| reviewer-location / U04 | Correct unlocated candidate then approve; race edit | Valid geometry/provenance reaches detail/index/history atomically |
| duplicate-merge / C09 | Preview/apply/retry/refresh both source identities | One survivor, old URLs and source/history retained |
| screening / D02 | Holes, touching edges, threshold boundary, partial layer, changed display LOD | Authoritative original-geometry result with correct uncertainty/provenance |
| artifact-upload / O01 | Interrupted/wrong-checksum upload, restart without local staging | No activation until verified; recoverable durable objects |
| readiness / O02 | Wrong migration/index/mode/token/origins; stale source | Fast accurate readiness, with liveness/source health separate |
| restore / O03 | Backup DB/manifests, restore second DB, fetch artifacts | Usable record/review/version/subscription/outbox/map state survives |
| release disclosures / O04 | Public catalog/source-use inventory review | Enabled sources have attribution/decisions; unresolved items visibly block release |

Each owner adds a small regression fixture and its scenario when implementing the feature. Do not build a huge test suite before the contracts exist, and do not mark future scenarios passing in advance.

## Race and recovery test mechanics

Use separate database sessions/processes and barriers, not sleeps alone, to force overlapping writes. Assert database state and public API state after both complete. Cover concurrent creation, decision conflict, ingestion versus review, duplicate publication, multiple matcher workers, lease expiry, and unsubscribe while queued.

Inject failures at named transaction boundaries and before/after SMTP acceptance. Verify all-or-nothing database state. The email test must acknowledge that acceptance followed by a client crash is externally ambiguous.

Run migrations from empty and from a copied previous schema/data state. Rebuild projections and reconcile stable IDs/counts. Restore into a new isolated target; never overwrite the user's preview. Check actual API/browser journeys after restore, including old public URLs and ready tile versions, rather than relying on a successful restore exit code.

## Upstream canaries — D01

Use the configured authoritative source URLs, with an explicit network opt-in and a global cap initially 20 requests. Read service metadata, supported CRS, object-ID field, required schema, one scoped count/ID sample and at most one small geometry batch per source. For agendas, fetch the listing and one bounded document sample only when needed, with byte/time caps.

Record URL, timestamp, HTTP status, selected schema/count/CRS observations, duration and sanitized errors. Rate-limit and honor retry guidance. Do not ingest into canonical working data, send mail, or equate a successful metadata request with complete fresh ingestion. Real source totals may change.

Ordinary CI must not fail because a city service is down. Canary reports distinguish source schema drift (actionable connector change), transient outage, changed coverage and local test failure. An optional scheduled job should alert only on a meaningful new failure/recovery, not produce repeated unchanged status messages. No scheduled job is installed by this planning task.

## Manual resident/reviewer acceptance — O03

- A resident finds a development by name, understands its status/source/date, sees usable streets/context, shares the current map and distinguishes partial/stale coverage.
- A resident submits an explicitly located or unknown-location tip, draws a watch, confirms it and later receives the correct locally captured test notification; unsubscribe works from the exact generated link.
- A reviewer opens original source evidence, corrects a location, rejects/approves a candidate, refreshes the same agenda without losing the decision and resolves a confirmed duplicate without losing links.
- On a 375–390px screen and with keyboard only, primary tasks remain possible; focus, labels, count announcements, contrast and non-map alternatives are checked. Automated accessibility checks supplement this inspection.
- Slow/offline/source-failure cases show honest loading/stale/unavailable states. A blank overlay is never described as evidence of no environmental concern.

## Completion evidence

A PR report lists exact commands and results, commit SHA, fixture/source hashes, schema revision, before/after behavior and any unrun check. Attach only relevant traces/screenshots/metrics. Docs-only plan validation is separate from implementation test results. A failure discovered during rehearsal becomes a focused follow-up PR with a reproducer; it is not waved through by the old green smoke suite.
