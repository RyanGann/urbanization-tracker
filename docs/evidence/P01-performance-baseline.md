# P01 — Reproducible real-stack performance baseline

Implementation and measurements are in progress; this is not a deployment-readiness claim.

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

Representative results, exact final fixture hashes, repeated-run comparison and final required checks will be recorded below before acceptance.
