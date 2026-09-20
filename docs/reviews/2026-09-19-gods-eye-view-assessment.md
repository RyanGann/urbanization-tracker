# God's Eye View assessment — September 19, 2026

**Recommendation: a good candidate for an optional 3D exploration view; defer a wholesale migration.** Keep Urbanization Tracker's FastAPI ingestion, source provenance, reviewed records, and operations. Compare a small God's Eye View integration with a direct Cesium view before choosing the long-term frontend.

I reviewed the original [bilawalsidhu/gods-eye-view repository](https://github.com/bilawalsidhu/gods-eye-view), including code and documentation at tree/commit `0d41b6be5490db1f10a171f238be75db4d4ec3b4`. This was a source-based assessment; I did not install or benchmark it locally. The repository was active and had roughly 38,600 stars at review time. Popularity establishes interest, not suitability for this application's workload.

## What it provides

God's Eye View is a Cesium-based globe for live public spatial feeds, terrain/imagery, navigation, annotations, and optional voice interaction. Current setup has a keyless path; photorealistic providers and voice introduce credentials, eligibility, quotas, or costs. Its architecture is vanilla JavaScript/Vite, rather than this project's React/TypeScript/MapLibre stack. [Project overview](https://github.com/bilawalsidhu/gods-eye-view#readme), [contributor architecture](https://github.com/bilawalsidhu/gods-eye-view/blob/main/CONTRIBUTING.md)

Reuse is more practical than merely copying the whole application: current exports include application lifecycle, map controllers, individual layer/source factories, and a GeoJSON layer helper. These use explicit services and lifecycle callbacks, so an adapter is feasible; it is not a drop-in React component. [Package exports](https://github.com/bilawalsidhu/gods-eye-view/blob/main/package.json), [reusable layer contract](https://github.com/bilawalsidhu/gods-eye-view/blob/main/docs/INFRASTRUCTURE-LAYERS.md)

## Pros and cons

| Benefits | Costs and limitations |
| --- | --- |
| Terrain and 3D context could help residents understand hillsides, landscape setting, and development near public land. | Imagery does not establish current construction status. Historical change, dates, and any actual viewshed analysis still need separate data and methods. |
| Existing navigation, annotations, layer management, and scene sharing offer useful design and engineering work to reuse. | React integration, selection/filter synchronization, layer styling, accessibility, and lifecycle cleanup need explicit work. |
| Published reuse interfaces allow a focused integration and retaining our backend. | A full fork carries unrelated aircraft/camera/ship features and ongoing upstream maintenance. |
| Strong potential for outreach and explaining a selected project spatially. | A dense globe interface and GPU/imagery demands may conflict with the original accessibility, mobile, and low-cost priorities; benchmark them. |
| Code is available under MIT terms, supporting modification and redistribution with its notice. | Bundled datasets, models, and provider imagery retain separate terms; the MIT code grant does not cover everything shown. [License](https://github.com/bilawalsidhu/gods-eye-view/blob/main/LICENSE) |

The largest mismatch is the product's core responsibility. Urbanization Tracker must discover fragmented local records, preserve evidence, distinguish proposals from approvals, retain reviewer decisions, and monitor changes. A spatial viewer does not supply those workflows. The current project's correctness and 129 MB overlay-response problems would still need fixing after a migration. This is an assessment of the integration, not a claim that every upstream feature was audited.

Upstream also explicitly describes a local-first exploration tool with a development/preview server, rather than a hardened hosted service. A public deployment still needs production serving, authentication for cost-bearing services, quotas, and monitoring. [Security model](https://github.com/bilawalsidhu/gods-eye-view/blob/main/SECURITY.md)

## Proposed experiment and required work

Use the existing `/api/map/development-records.geojson` contract to supply a separate **3D Explore** route or small companion app. Keep record details, participation, and review in the current application. Link selected features using their existing `public_id`. Ship only development and relevant environmental layers; retain provider attribution and disable unnecessary feeds.

| Stage | Concrete output | Estimated developer effort |
| --- | --- | --- |
| Feasibility spike | Pin upstream; create a Huntsville scene with a bounded real-data sample, subdivision polygons, permits, one simplified environmental overlay, and links to existing record details. Compare a direct Cesium implementation. | 3–5 days |
| Useful pilot view | Integrate actual filters, provenance/confidence/freshness, layer ordering, correct ground placement, shareable selection, keyboard/list fallback, and geometry/imagery budgets. | 2–4 additional weeks |
| Hosted hardening | Production serving, applicable provider terms, attribution, spend limits, mobile/accessibility checks, integration tests, and an upstream-update strategy. | 1–2 additional weeks |

These are planning estimates for one developer familiar with the project, not fixed quotes. They exclude the current backend repairs, new environmental datasets, and a historical-change pipeline. A full replacement would also require porting or reconnecting participation, reviewer operations, state, routes, tests, and deployment; budget at least 6–10 weeks overall and revisit after the spike.

Advance only if the prototype helps answer a real resident question better, retains source/uncertainty information, performs acceptably on ordinary hardware, and has an acceptable operating budget. A direct Cesium view may provide most of the needed 3D benefit with less inherited application code. Keep a usable 2D/list view either way. The first implementation priority remains making the existing Huntsville data trustworthy and usable.
