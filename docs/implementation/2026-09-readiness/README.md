# Urbanization Tracker implementation handoff

Prepared September 19, 2026 from the [project review](../../reviews/2026-09-19-project-review.md) and code at `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`.

**Recommendation: finish a dependable Huntsville pilot on the current stack, with real API/PostGIS tests and bounded map delivery.** This package contains **38 PR-sized guides**, including **nine performance PRs**, shared contracts, an execution order and acceptance gates. All work is **planned**. This task created documentation, not application fixes, deployments or passing results for new tests.

The full roadmap includes later environmental goals and an optional 3D experiment. It is not a requirement to finish all 38 PRs before seeing improvement: U00 fixes filter visibility early, and P02 removes the startup geometry download early. The user has the existing site open in the side browser; this planning task has not revalidated browser automation or changed that running preview.

## Read and dispatch

- [Performance plan and cheaper-agent assignment](PERFORMANCE.md): fixed design, sequence, geometry safeguards, proposed budgets and benchmark protocol.
- [Shared API/data contracts](CONTRACTS.md): identity, transactions, review revisions, catalog/tiles, viewport queries, coverage and outbox behavior.
- [Live API and browser testing plan](TESTING.md): isolated real services, upstream canaries, regression matrix, recovery and resident/reviewer acceptance.
- [Agent dispatch instructions](DISPATCH.md): copyable handoff, dependency/branch rules, shared-file ownership and lead review.
- [Machine-readable plan](plan.json): IDs, dependencies, status, guide paths, gates and implementation evidence placeholders.

Start T01 and S01. After T01, start C01 and P01. Then dispatch U00, C02 and P02 as their dependencies permit. Continue two coordinated tracks: durable publication/review/alerts and performant map delivery. Do not assign an agent 'make the site production-ready'; assign one guide with its dependency SHAs and acceptance checklist.

No specific model purchase or cloud plan is needed to use these guides. Routine coding agents can handle bounded client/test tasks; the lead reviews migrations, identity, geometry, transactions and delivery semantics.

## Architectural decisions

Keep React, MapLibre, FastAPI and PostgreSQL/PostGIS. Replace full environmental GeoJSON downloads with a small catalog and immutable versioned vector tiles generated from indexed display geometry. Preserve original geometry for screening and provenance. Serve developments through a bounded viewport summary query and fetch detail on demand.

Correct the record lifecycle before trusting alerts or spatial indexes: explicit live/demo modes, stable source identity, durable review revisions, one transactional publication service and a durable alert outbox. The existing generic collection tables can be made safe incrementally; a wholesale rewrite into every unused normalized table is unnecessary.

Use actual HTTP services and PostGIS for integration tests. Keep small live-source probes separate from deterministic CI. Retain the 2D application while evaluating God’s Eye View only as a time-boxed optional experiment after the pilot; see the [original assessment](../../reviews/2026-09-19-gods-eye-view-assessment.md).

## Acceptance gates

| Gate | Evidence required | What it enables |
| --- | --- | --- |
| G0 — trustworthy baseline | Real-stack harness, explicit data modes, dependency update, measured baseline | Safely implementing and comparing changes |
| G1 — dependable data lifecycle | Stable IDs, complete declared source scope, transactional writes, durable review/publication, located records, matching/outbox, verified artifacts and screening | Trustworthy canonical data and internal workflows |
| G2 — usable performant map | Real default/filter behavior, bounded tiles/queries, basemap/search, location picker, shareable state, accessibility and measured budgets | A useful resident/reviewer preview |
| G3 — restricted-alpha readiness | G0–G2, restored backups, source-use decisions, reviewer protection, correct web/API links, operational monitoring and an evidence-based rehearsal | A concrete candidate for an explicitly requested rollout |
| G4 — original environmental expansion | One protected/refuge layer and verified two-year land-cover/impervious comparison | Broader environmental utility after pilot stability |
| Optional — viewer decision | Five-day measured God’s Eye View experiment | A justified decision about optional 3D |

A PR can merge before its broader gate is complete if its intermediate state is explicit and safe. P02's temporarily unavailable environmental controls do not satisfy G2. Green mocked tests, a hosting template, a liveness response or a fast empty canvas do not satisfy G3.

## Traceability to the review

| Review finding/recommendation | Owning guides |
| --- | --- |
| Huge environmental payload and repeated map work | P01–P09 |
| Empty canonical store becomes demo data | C01 |
| Future publications do not notify watches; missing history | C06–C08, S03 |
| Agenda refresh erases decisions | C03–C05 |
| Processed rows offer actions that return 404 | C05 |
| Completed/proposed/submission records hidden; empty filter means all | U00, P07/P08, U01 |
| Seed layer IDs, no basemap/search, no shareable state | P02/P06, U01/U02 |
| Partial/stale data and weak source paging | D01, U01, D02 |
| Vulnerable frontend and unpinned Python dependencies | S01, T01 |
| Lost concurrent writes and missing real-database tests | C02, T01, each owning regression PR |
| Public input/opt-in/unsubscribe/retry problems | S02/S03, C07/C08, U03 |
| Missing reviewer geometry correction/duplicate merge | U04, C09 |
| Intended storage URIs without uploads; unverified recovery/hosting | O01–O03 |
| Code license and source/provider use decisions | O04 |
| Missing protected/refuge and land-cover change goals | E01–E04 |
| God’s Eye View suitability | X01, after core stability |

## Start and immediate fixes

| Guide | Depends on | Review |
| --- | --- | --- |
| [T01: Run integration tests against the real API and PostGIS](T01-real-api-postgis-harness.md) | Ready to start | Lead review |
| [S01: Patch frontend dependencies and verify map compatibility](S01-frontend-dependency-update.md) | Ready to start | Routine with visual review |
| [C01: Distinguish live data, demo fixtures, empty collections, and unavailable stores](C01-explicit-data-modes.md) | T01 | Routine coding agent |
| [P01: Establish a reproducible map performance baseline](P01-performance-baseline.md) | T01 | Routine coding agent |
| [U00: Make current map filters show the intended records](U00-immediate-filter-correctness.md) | C01 | Routine coding agent |
| [P02: Serve a small layer catalog and stop eager bulk overlay downloads](P02-layer-catalog-startup-relief.md) | P01, C01 | Routine coding agent |

## Durable data and review

| Guide | Depends on | Review |
| --- | --- | --- |
| [C02: Introduce shared transactions and safe item mutations](C02-transactional-store-foundation.md) | T01, C01 | Lead review |
| [C03: Preserve source identity and merge ingestion batches safely](C03-stable-source-identity.md) | C02 | Lead review |
| [D01: Fetch a declared pilot scope completely and report source coverage](D01-source-scope-pagination-canaries.md) | C03, T01 | Lead review |
| [C04: Retain agenda documents and reviewer decisions across refreshes](C04-agenda-revision-retention.md) | C02, C03 | Lead review |
| [C05: Make review actions explicit, durable, and revision checked](C05-review-action-policy.md) | C02, C04 | Routine with lead review |
| [C06: Publish canonical changes and durable history in one transaction](C06-publication-events-history.md) | C03, C04, C05, S02 | Lead review |
| [S02: Validate geometry and limit public write abuse](S02-public-input-validation.md) | C02 | Lead review |
| [U04: Let reviewers validate and correct a candidate location](U04-reviewer-geometry-correction.md) | C05, S02, U02, C06 | Lead review |
| [C09: Merge confirmed duplicates without losing URLs or provenance](C09-manual-duplicate-resolution.md) | C06, U04, C07 | Lead review |
| [D02: Calculate environmental screening from complete canonical geometry](D02-authoritative-spatial-screening.md) | D01, P04, C06 | Lead review |

## Watch and notification reliability

| Guide | Depends on | Review |
| --- | --- | --- |
| [C07: Generate future-change watch alerts through a durable outbox](C07-publication-watch-matcher.md) | C06, S02 | Lead review |
| [S03: Confirm watch subscriptions and make unsubscribe links work](S03-watch-confirmation-unsubscribe.md) | C07, S02, C08 | Routine with lead review |
| [C08: Deliver outbox messages with leases, retries, and clear failure states](C08-delivery-leases-retries.md) | C07 | Lead review |

## Remaining map performance

| Guide | Depends on | Review |
| --- | --- | --- |
| [P03: Import versioned environmental geometry into indexed PostGIS storage](P03-canonical-environmental-storage.md) | T01, C02, P02 | Lead review |
| [P04: Prepare display geometry and activate complete layer versions atomically](P04-environmental-display-derivatives.md) | P03 | Lead review |
| [P05: Serve bounded, cached environmental vector tiles](P05-versioned-vector-tile-api.md) | P04 | Lead review |
| [P06: Render catalog-driven vector overlays without bulk GeoJSON](P06-vector-overlay-client.md) | P02, P05, S01 | Routine coding agent |
| [P07: Add an indexed viewport query for development summaries](P07-bounded-development-map-api.md) | C06, U00 | Lead review |
| [P08: Query developments by viewport and avoid redundant map work](P08-viewport-map-client.md) | P07, S01 | Routine coding agent |
| [P09: Enforce map payload and performance budgets in CI](P09-performance-regression-gates.md) | P06, P08, U01, U02 | Routine coding agent |

## Map and participation usability

| Guide | Depends on | Review |
| --- | --- | --- |
| [U01: Make filters complete and map state shareable](U01-filters-shareable-state-coverage.md) | P06, P08, D01, U00 | Routine coding agent |
| [U02: Add a contextual basemap and local record search](U02-basemap-record-search.md) | P08, S01 | Routine with visual review |
| [U03: Replace shared coordinate inputs with explicit location selection](U03-participation-location-picker.md) | S02, U02 | Routine with visual review |

## Restricted-alpha operations

| Guide | Depends on | Review |
| --- | --- | --- |
| [O01: Upload and verify ingestion artifacts before activating data](O01-durable-artifact-uploads.md) | C02 | Lead review |
| [O02: Update hosted configuration and readiness checks for the new contracts](O02-deployment-guardrails.md) | S01, C01, P05, P07, O01, S03 | Lead review |
| [O04: Prepare code-license, data-use, and public disclosure decisions](O04-release-data-use-decisions.md) | D01, P02 | Owner decision after prepared evidence |
| [O03: Rehearse migration, recovery, and resident/reviewer workflows](O03-restricted-alpha-rehearsal.md) | C08, C09, U03, D02, P09, O02, O04, D01 | Lead review |

## Environmental goals after the pilot

| Guide | Depends on | Review |
| --- | --- | --- |
| [E01: Add one authoritative protected-land or refuge layer](E01-first-protected-land-layer.md) | O03, P04, D02 | Lead review |
| [E02: Choose a comparable land-cover product and lock a small fixture](E02-land-cover-source-spike.md) | O03 | Lead review |
| [E03: Build versioned pilot raster tiles and comparison summaries](E03-pilot-raster-artifacts.md) | E02, O01, P05 | Lead review |
| [E04: Show a two-year land-cover and imperviousness comparison](E04-land-cover-comparison-ui.md) | E03, U01 | Routine with visual review |

## Optional viewer experiment

| Guide | Depends on | Review |
| --- | --- | --- |
| [X01: Evaluate God’s Eye View with one bounded integration experiment](X01-gods-eye-view-spike.md) | O03, P09 | Lead review |

## Assumptions, decisions and limits

Huntsville remains the pilot; default map filters include all supported published statuses/types. ArcGIS auto-published valid entries are read-only audit rows, while manual submissions/agendas require review. Unknown locations stay unlocated. Environmental context is screening-level and includes coverage/uncertainty.

Performance targets and resource profiles are proposed, not achieved. Source counts/latency in the review are dated observations. The harness will use generated fixtures and disposable copies; it will not alter the saved June dataset or the user's existing preview.

The implementation needs no immediate user clarification. O04 prepares concrete choices for a root code license, source-use restrictions and a hosted basemap/storage provider if applicable. Unresolved source permission blocks that source's public display; an unselected code license blocks promoting licensed reuse. External deployment, paid resources and real recipient mail remain later actions.

Waterways, watersheds, broader protected-land/habitat sources, additional jurisdictions, generalized raster analytics and a full 3D migration remain outside the first pilot handoffs. E01 and E02 deliberately establish one verified source/product at a time before expanding.

## Plan validation

Validation passed for all 38 guide files, nine performance guides, the acyclic dependency graph, index/manifest agreement, required guide sections and all local links across the package and updated entry documents. Whitespace checks passed. The temporary local validator is under tmp/validate-readiness-plan.cjs; it checks documentation only and is not a new application test harness.

Application tests were not rerun for these documentation-only changes. The previously reviewed checks remain historical evidence; live API, new performance budgets and launch acceptance are still work for the implementation PRs.
