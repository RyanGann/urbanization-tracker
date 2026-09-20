# Urbanization Tracker review — September 19, 2026

**Assessment: a substantial working prototype, with verified correctness and usability gaps before a dependable public alpha.** The remaining work includes application behavior as well as hosting. Preserve the existing project and finish a narrow Huntsville pilot before expanding its scope.

Reviewed local and remote `main` at `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34` (July 19), the original May 20 planning conversation, architecture and phase documents, the twelve merged pull requests, source/ingestion/storage/UI code, saved artifacts, current dependency advisories, and the existing checks. This is a focused readiness review, not an exhaustive security audit.

## Goals and prior work

The original goal was a low-cost, accessible public-good map of development and landscape change: existing developed/impervious land, proposed development, waterways and wetlands, protected lands, refuges, and habitat. Source attribution, confidence, freshness, review, and uncertainty were essential. The user explicitly selected Huntsville and FastAPI after an initial Austin/Django proposal.

The implementation provides React/TypeScript/MapLibre, FastAPI, ArcGIS and agenda-PDF ingestion, record details, review actions, submissions, watch subscriptions, SMTP delivery machinery, source monitoring, generic Postgres collection storage, migrations, CI, and a Render Blueprint. These are useful assets worth keeping.

May established the prototype and ingestion. June's work addressed persistence, source health, geometry calculations, artifact manifests, and operational controls. July prepared private-alpha Render configuration, exposed store status, split frontend routes, and corrected a Blueprint field. The last change explicitly fixed configuration validation without provisioning resources. See [private-alpha PR #9](https://github.com/RyanGann/urbanization-tracker/pull/9) and [Blueprint PR #12](https://github.com/RyanGann/urbanization-tracker/pull/12).

The latest README already distinguishes code completion from a verified service. The earlier completed-phase checklist overstates some end-to-end behavior: for example, it marks ongoing alerts complete, although later publications do not generate alerts. The [July 19 CI run](https://github.com/RyanGann/urbanization-tracker/actions/runs/29680202357) succeeded; that did not establish production readiness.

| Original goal | Present state |
| --- | --- |
| Local development records with provenance | Working ingestion and detail/API foundation; map and review gaps below |
| Environmental context | Two actual saved overlays: floodplain and wetlands; other seed overlays are demonstration fixtures |
| Impervious surface and land-cover change | Planned; no implemented NLCD/change layer or historical comparison workflow found |
| Protected/public lands, watersheds, refuges, critical habitat | Research/design exists; corresponding production ingestion/layers not implemented |
| Reviewer validation and audit | Basic decisions exist; geometry editing, duplicate merging, and preservation across refreshes remain incomplete |
| Ongoing monitoring | Watch creation and SMTP queue delivery exist; future-change alert generation is incomplete |
| Public usability | No contextual basemap or place search; coordinate-entry watch areas; map state is not shareable through the URL |
| Durable spatial storage | Postgres JSON collections exist; normalized PostGIS querying is still a later step |

## Verified findings

**1. Real overlay delivery is too large for this UI.** The saved environmental JSON is 365,813,217 bytes. One local API request returned **128,934,218 bytes in 39.22 seconds**, before client rendering. The map downloads both full overlays even while they are hidden. This was one measurement on the current machine, with other checks running, not a controlled benchmark. The response size itself is conclusive. Serve clipped, simplified geometry or tiles by viewport/zoom; use caching and compression. Moving this payload to a different map engine would retain the underlying problem. [API overlay loading](../../apps/api/app/seed_store.py#L150)

**2. An empty canonical collection silently becomes demo data.** In an isolated probe, a stored empty development-record list returned four seed records. The same truthiness fallback follows the Postgres read path. A new or legitimately empty deployment can therefore display invented example developments. Require an explicit demo mode, distinguish missing data from an empty authoritative result, and fail visibly when production data is unavailable. [Fallback](../../apps/api/app/seed_store.py#L93)

**3. Watch subscriptions do not monitor later publications.** A probe created a watch, then published a matching reviewed submission: one record matched, but zero alerts were queued. Matching runs when the watch is created; publication/ingestion does not invoke it. Implement new/changed-record events, version-aware deduplication, and a transactional delivery queue. Source-ingested records also generally expose a current snapshot rather than accumulated change history. [Watch creation](../../apps/api/app/phase3_store.py#L244)

**4. Agenda refresh overwrites reviewer decisions.** A rejected candidate became pending after the same replacement operation used by ingestion. The last three discovered documents replace the agenda collections, also limiting retained context. Merge by stable source/document/item identity and preserve review decisions, versions, and older documents across unchanged refreshes. [Replacement](../../apps/api/app/phase3_store.py#L353)

**5. Processed ArcGIS records appear in the queue but cannot use its review actions.** A needs-info request for an actual processed staged record returned 404. The lookup checks seed records and then Phase 3 records, omitting the canonical processed staged collection. Either make those records explicitly read-only if they are automatically published, or persist review actions against the correct store. [Lookup](../../apps/api/app/seed_store.py#L178)

**6. Map defaults omit important data.** The default query returns 824 of the 1,324 saved records, excluding the 500 completed county subdivisions. Proposed status and public submissions have no normal positive selection controls; a newly published submission was absent under the map's default filters. Deselecting all options instead removes the API restriction, an unintuitive workaround. Overlay defaults use seed IDs that do not match the two ingested IDs, so actual environmental layers initially remain off. The map style contains only a background, with no streets, imagery, or place labels. Correct these behaviors together and add a clear legend, coverage/freshness banner, place search, and shareable state. [Map defaults](../../apps/web/src/pages/MapPage.tsx#L20), [map style](../../apps/web/src/components/DevelopmentMap.tsx#L22)

**7. Freshness and completeness need public disclosure.** All saved development records were last checked June 19. The source monitor correctly returned 503 with all six sources stale. Saved source counts show only 500 of 17,967 permits, 2,000 of 18,195 wetlands, and 500 of 7,517 county subdivisions fetched. Those are counts from the June snapshot, not current source totals. Caps are intentional development defaults; users need an explicit time/geographic coverage contract, and environmental screening cannot assume omitted features are absent. Refresh sources after defining that contract. [Ingestion limits](../../apps/api/app/ingestion/pipeline.py#L37)

**8. Dependencies need an update pass.** `npm audit --omit=dev` reported four affected production packages: one critical and three moderate, including transitive overlaps. The critical MapLibre advisory concerns untrusted attribution HTML; this app currently uses fixed attribution, so this review did not demonstrate an exploitable path. Still, update and validate before introducing third-party basemaps. The maintainer identifies 6.4.1 as the first patched release; the current lock uses 4.7.1, so migration testing is required. React Router advisories also need triage. [MapLibre maintainer advisory](https://github.com/maplibre/maplibre-gl-js/security/advisories/GHSA-jrc7-96c5-q579), [React Router advisory](https://github.com/advisories/GHSA-jjmj-jmhj-qwj2)

## Other launch work

Whole-collection database replacement following separate reads creates a risk of lost concurrent submissions, reviews, or ingestion updates. This is a code-review finding, not a reproduced Postgres race. Add atomic record-level writes or locking and real database integration checks. Existing persistence tests mostly mock database operations.

Public submissions/watch endpoints have no application-level abuse controls, verified email opt-in, or robust geometry validation. The submission form also borrows the watch form's default rectangle without a separate location picker. Finish those flows before inviting public submissions or sending mail. Keep delivery disabled until monitoring, unsubscribe, opt-in, retries, and provider handling are verified.

The two documented Render URLs returned 404 during this review. This does not establish whether another hostname or account has a deployment. No hosted Postgres, PostGIS migration, backup restore, edge reviewer policy, or monitoring configuration was verified. The raw-artifact manifest records intended storage locations but does not upload artifacts. The Blueprint deliberately disables ingestion and email pending that work.

Revisit the source-redistribution questions already recorded in the project's source notes before publishing bulk data. The repository describes itself as open source but has no root LICENSE file; select and add a license before promoting reuse. These are project follow-ups, not conclusions about data-use permissions.

## Validation and preview

Fresh checks passed: **60 backend tests, backend Ruff and mypy, 4 web unit tests, the TypeScript/production build, and 3 Chromium smoke tests**. Chromium had to be installed locally before the smoke suite ran. Its tests mock the API; they do not exercise actual overlay volume, ingestion-to-review behavior, source refreshes, or production database recovery. Backend dependencies resolved afresh because no Python lock file is present; pin a reproducible set.

Isolated probes additionally reproduced findings 2–5 and the hidden published-submission case. These did not modify the original saved data. Temporary diagnostic code is in review-diagnostics.py (local, untracked diagnostic).

The website is running at [http://127.0.0.1:5173](http://127.0.0.1:5173), with the actual FastAPI backend at [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health), using an isolated copy of the saved snapshot. The web process is PID 2656; the container is `urbanization-tracker-review-api`. Outbound email and source ingestion are disabled. Local preview writes are disposable container data.

**In-app visual inspection remains incomplete:** the installed browser integration failed during startup with `Importing module "node:process" is not allowed in node_repl`. It could not open a tab or capture the current page. The running URL is available for manual opening in the app. Passing the separate repository smoke tests is not an in-app visual review. Mobile/accessibility behavior and actual map rendering still require inspection together.

## Recommended sequence

1. **Correct the data lifecycle:** empty-store behavior, durable review decisions, processed-record actions, publication/change alerts, and concurrent writes. Add regression coverage using the actual API and a real Postgres/PostGIS test environment.
2. **Make the Huntsville map usable:** update dependencies, add a basemap, fix filters/layer defaults, reduce overlay payloads, disclose stale/partial coverage, and replace coordinate-only participation with a location picker. Agree on a representative desktop/mobile performance budget.
3. **Verify a restricted alpha:** fresh reviewed data, object-storage uploads, database migration/restore, reviewer protection, and source/error monitoring. Run repeat ingestion and publication-to-alert checks. Define a small acceptance checklist around resident and reviewer tasks.
4. **Add the missing environmental goals deliberately:** prioritize land-cover/impervious change plus protected lands/refuge context, with source versions and dates, before broad geographic expansion.
5. **Evaluate 3D as a bounded experiment:** see the accompanying God's Eye View assessment. Retain the current API and provenance model whichever visualization wins.
