# P01 — Reproducible real-stack performance baseline

The legacy representative workload fails on both desktop and mobile. This PR establishes measurement and failure evidence; it is not a deployment-readiness claim.

## Reproduce

Use Node 22+, Docker Compose, and the repository lockfiles. From the checkout root:

```text
node --test apps/web/e2e/performance/metrics.test.mjs
node scripts/run-integration.mjs --suite performance --scenario functional --profile desktop --smoke
node scripts/run-integration.mjs --suite performance --scenario representative --profile desktop
node scripts/run-integration.mjs --suite performance --scenario representative --profile mobile
```

Repeat each representative command for variation. `--smoke` explicitly uses two cold contexts, two interaction cycles and two requests per endpoint/concurrency; it is a functional check, not a latency baseline. Normal runs request ten fresh contexts, twenty interaction cycles, and one hundred requests per endpoint at concurrency one and five. Two failed cold samples or API requests stop the affected scenario; completed and unrun samples remain explicit. An API outage fails immediately, rather than waiting for nonexistent UI. Timing budgets do not gate CI in P01; the small real-data functional precheck does.

The runner prints its randomized project and artifact directory. It reuses T01's private PostGIS/API/web/mail/browser stack, loopback gateway, labels, bounded waits, token redaction and recovery record. Only that project is cleaned. Before measurement the DB is limited to two CPUs/2 GiB and API to one CPU/1 GiB. Fixture seeding/geometry validation is outside measured time and outside the API memory limit.

`tmp/integration/<run>/` contains the fixture manifest, browser/API raw samples, screenshots, SQL plans, sampled container resource records, available cgroup lifetime memory peaks, image identifiers, commit SHA, dirty-tree indication and cleanup result. The large generated geometry stays ignored. An interrupted run retains incremental browser samples and exact T01 recovery instructions. On Windows an OS force-kill cannot execute JavaScript cleanup; inspect labels and use the recorded recovery command.

## What is measured

Read-only map probes exist only with `VITE_PERFORMANCE_MARKS=true`. Ordinary builds incur no extra map-query or idle-listener work. The probe checks a small region at a known fixture coordinate and returns identity/camera/visibility facts, not map mutation methods or full dense geometry. Readiness requires a known development, list, and enabled environmental feature; a physical canvas click must open the matching popup and selected-record panel. Missing marks/features and failed real APIs are failures. No API interception or synthetic map events are used.

First-useful timing ends at actual parsed records, committed list, and observed rendered feature. Context timing ends at the known overlay render. Screenshots and interactions happen afterward. A map outside the initial viewport reports null initial-usefulness timing and a failed cold sample; scrolling is only permitted for the separately recorded functional interaction and warm checks. Catalogs and tiles are not implemented on this baseline, so their metrics remain null.

Fresh browser contexts have HTTP cache disabled; the database is warmed by seeding/API verification. These are browser-cold, database-warm runs. Desktop viewport is 1440×900. Mobile is 390×844 with Chromium 4× CPU throttling, 10,000,000 bit/s down, 1,000,000 bit/s up and 100 ms latency. The empty local map style removes external provider dependencies; basemap/glyph/sprite traffic is reported separately and is currently absent.

API response bodies are streamed through the actual content decoder. Encoded body bytes exclude headers/framing; decoded bytes count decompressed content. CDP transfer totals are reported separately from body bytes and cache/failure state. Missing Content-Length never becomes a zero-byte response. Real gzip/chunked and stalled-response tests verify these distinctions. API bodies have a 256 MiB decoded/encoded safety bound and a 120-second request limit; exceeding either is a failed sample, not a successful latency.

Warm cycles physically pan and zoom, filter and restore results, select a known feature and toggle an actual overlay. They retain action durations, request churn, long tasks and browser performance/heap metrics. SQL plans cover the legacy collection reads and explicitly exclude Python JSON work. Docker stats are samples; cgroup peaks are lifetime peaks including warmup, not a claimed steady-state reading. Missing measurements remain null.

## Optional disposable snapshot

Copy the desired processed files to a new directory inside this checkout's ignored `tmp` first. The directory must contain `development_records.json`, `environmental_overlays.json`, and `source_health.json`. Then run:

```text
node scripts/run-integration.mjs --suite performance --scenario snapshot --snapshot-dir tmp/my-disposable-copy/processed --profile desktop
```

The snapshot helper resolves the directory and rejects paths outside this checkout's `tmp`. It reads source files without modifying them, records source checksums, and creates a separate fixture with only benchmark feature-identity properties added. No original June snapshot was refreshed or benchmarked in this PR. A generated-copy verification proved source checksums unchanged and rejection of an input outside `tmp`.

If the copy has no record allowed by the current default filters or no enabled legacy overlay, preparation fails with retained checksums. It does not enable hidden data or claim a readiness time. Snapshot payloads and artifacts may contain private/source data: keep them ignored and local. The required CI command uses only generated public synthetic fixtures.

## Validation checkpoint

The corrected desktop functional run at `97fca6e` passed two fresh loads, two complete warm cycles and both real endpoints at concurrency one/five. Artifact: `tmp/integration/2026-09-20T03-06-14-304Z-819b3502`; cleanup removed. Lead inspected its selected-record screenshot. That small smoke run is not a representative performance result. Earlier failed prechecks revealed transformed string feature IDs and overlapping click targets; stable fixture properties and an isolated known development corrected those assertions.

## Controlled reference results

The representative legacy path failed both desktop runs: the API was OOM-killed (exit 137) while loading the full environmental collection under its 1 GiB RAM limit. Neither run achieved a useful map with enabled environmental context. Both completed cleanup successfully. These failures establish the baseline; they do not pass any readiness or performance budget.

| Run | Application/reporter SHA | Result | Workload completed / requested |
| --- | --- | --- | --- |
| [Desktop 1](P01/desktop-1/summary.json) | ff59ba671a362974e81d8b7fd6e1ddf430fddb33 | API OOM, no usable-map latency | 2/10 cold loads, 0/20 warm cycles, 14/400 API attempts |
| [Desktop 2](P01/desktop-2/summary.json) | 930e2556a81e977e3fb2142cfadbee31fe6a2e5d | Overlay readiness timed out, then API OOM | 2/10 cold loads, 0/20 warm cycles, 14/400 API attempts |
| [Mobile 1](P01/mobile-1/summary.json) | 59d6e8b7c6b5675e0b682971e6a68680d9400fae | Overlay readiness timed out, then API OOM | 2/10 cold loads, 0/20 warm cycles, 14/400 API attempts |
| [Mobile 2](P01/mobile-2/summary.json) | 6d26c3f403abf7909276bcb002b5cb1ed2bf1102 | Overlay readiness timed out, then API OOM | 2/10 cold loads, 0/20 warm cycles, 14/400 API attempts |
| [Functional fixture A](P01/desktop-functional/summary.json) | 294a995d0de2f8b4278fcb938816e24591eedd7b | All functional checks passed | 2/2 cold loads, 2/2 warm cycles, 8/8 API attempts |

The two-failure stop rule avoided hundreds of repeated requests to an unavailable API. Successful-latency distributions remain empty/null; failed requests are not included in a p95. Of 430 requested representative operations, each desktop run attempted 16 and left 414 unrun. Raw samples, failures, SQL plans, fixture manifests, image versions, resource samples and cleanup records are alongside each summary. The small fixture's two samples prove the harness works, not the representative budgets.

Run 2 spent longer at its RAM limit before the OOM; sampled block I/O rose while CPU use varied. Its captured effective Docker MemorySwap limit was 2 GiB combined RAM plus swap, allowing up to 1 GiB swap beyond its 1 GiB RAM cap. No resource limits changed between runs. Run 1 did not capture an effective swap limit, so that field remains unknown. Docker describes this combined limit and the possible performance penalty in its [resource constraints documentation](https://docs.docker.com/engine/containers/resource_constraints/). Later runs capture the effective limit automatically. Exact cgroup API peaks are unavailable after the process exits; sampled 1 GiB use is not presented as an exact peak.

Both runs used synthetic fixture B: 1,324 developments, 4,000 environmental features, 4,451,671 environmental coordinate pairs, and 103,055,694 UTF-8 fixture bytes. SHA-256: `6cc899d1db3110a1278f77a2352c11b0aba8e43f9a95e1a4be58409c7fc18150`. Fixture A has 32 developments, 16 environmental features, 572 coordinate pairs and 46,545 bytes; SHA-256: `cc7114c31fa8dbce0374279ccc4b4eabb8bebf021513719781c8ba7312c1edc3`. The complete fixture byte count includes both developments and context; it is not an observed overlay HTTP response size. Repeated generation produced identical hashes, and PostGIS validated accepted geometry before seeding. Invalid and unlocated diagnostics remain quarantined because the existing published schema cannot represent an unlocated record.

Reference host: Windows 10.0.26200, AMD Ryzen 5 2600 (12 logical CPUs), 17,129,902,080 bytes RAM, Kingston SA400S37240G SATA SSD. Docker 29.8.0 exposed 12 CPUs and 12,542,230,528 bytes RAM. Browser: Chromium 148.0.7778.96; PostgreSQL 16.4/PostGIS 3.4. The first desktop database occupied 54,186,467 bytes. The existing preview and an unrelated database remained running; this was not an otherwise idle machine. Variation cannot be attributed solely to application changes or browser profile.

The original database artifact's note incorrectly says JSONB; the actual legacy payload column is JSON. The reporter wording is corrected in later runs. Archived raw evidence is preserved unchanged. Reporter fixes between desktop runs tightened rendered-overlay toggle proof and mandatory resource sampling; they did not optimize the application path.

## Archive reproducible evidence

```text
node scripts/performance/archive-evidence.mjs --run tmp/integration/<completed-run> --label desktop-1 --dry-run
node scripts/performance/archive-evidence.mjs --run tmp/integration/<completed-run> --label desktop-1
```

Only completed, cleaned synthetic A/B runs with matching fixture hashes can be archived. The helper copies selected JSON evidence and removes local absolute paths and unrelated container names. Snapshot data, generated full geometry, logs, environment files and screenshots remain local. Existing archive names are never overwritten.

The first mobile repetition also ended in API OOM (exit 137), after the enabled-overlay wait timed out. It used SHA `59d6e8b` with archive-helper/evidence work present in the working tree; the application path was unchanged. Its effective API policy was 1 GiB RAM and 2 GiB combined RAM/swap. Raw run: `2026-09-20T03-37-33-892Z-65f330b2`; cleanup removed. The second mobile repetition at `6d26c3f403abf7909276bcb002b5cb1ed2bf1102` had the same OOM outcome, sample counts, and effective resource limits. Neither profile produced a successful representative latency; comparison across devices is therefore limited to the repeated failure, not a speed ratio. All four representative projects were removed.

## Final integration checks

C01 was merged into this branch after the legacy baseline measurements; its data-mode/error handling is retained together with benchmark instrumentation. All four archived baseline application SHAs predate that integration, and are explicitly identified rather than described as final-head latency measurements.

Ten affected measurement tests pass, including streamed gzip byte counts, timeout failure, mandatory resource sampling, conventional medians, and awaiting delayed worker size accounting. Worker response transfer uses completed Playwright encoded body plus response header sizes when page-target CDP omits completion, with explicit provenance. Unknown decoded body sizes remain null. The [Playwright request size contract](https://playwright.dev/docs/api/class-request#request-sizes) defines those fields. Older archived smoke medians used nearest-rank p50; their raw samples are preserved, and no two-sample latency budget is claimed.

Final combined real-stack functional verification and CI are pending. Required CI includes the performance functional precheck, T01 real API/browser smoke, and C01 data-mode scenario.
