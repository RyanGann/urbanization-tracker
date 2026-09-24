# O04 release decision sheet — owner review

Prepared 2026-09-24 UTC and reconciled against merged D01 main `f450108`. [Source-by-source evidence](O04-source-use-inventory.md) is the companion record. These are proposed decisions and copy, not selected terms, a legal determination, or a launch approval. No root `LICENSE` exists and no source redistribution clearance is recorded by this document. D01 adds scoped staging and canaries, not source activation or rights clearance; its final [coverage evidence](D01-scoped-ingestion.md) remains a separate data-quality record.

## 1. Code license: owner choice required

**Recommendation:** If broad civic reuse and integration are the goal, choose **MIT for this repository's original code only after resolving the PyMuPDF dependency** by replacing its PDF extraction use with an appropriately licensed implementation or obtaining a reviewed commercial arrangement. MIT is short, familiar, and allows downstream public-interest and commercial reuse; its notice must travel with copies. [OSI MIT text](https://opensource.org/license/mit). The recommendation does not cover City/FEMA/USFWS data, generated geometry, or the hosted basemap.

The dependency check is material, not cosmetic. `apps/api/pyproject.toml` and both API locks include `pymupdf` (locked at 1.28.2); `apps/api/app/ingestion/agenda.py` imports `fitz` for PDF text. [PyMuPDF's maintainer](https://github.com/pymupdf/PyMuPDF#licensing) states AGPL v3 for open-source use or a separate commercial license. An MIT label on this repository would not erase that dependency's terms or settle obligations for a combined distributed/hosted application. `psycopg[binary]` is another runtime dependency; [Psycopg's package metadata](https://pypi.org/project/psycopg/) identifies LGPL-3.0-only. The JS lock records per-package license metadata, but this sheet is **not** an exhaustive dependency/license audit, and transitive Python, binary wheels, fonts, data, notices and distribution images still need review.

| Owner path | Why choose it | Work before root license/public reuse |
| --- | --- | --- |
| **A — MIT after PyMuPDF resolution (recommended)** | Maximizes reuse and minimizes contribution friction. | Replace or license PyMuPDF; compare PDF extraction fidelity in the agenda tests/real fixture; inventory direct and transitive distributions, preserve their notices; confirm ownership/contributor permissions; add exact OSI MIT `LICENSE`, copyright holder/year and README/package metadata after owner selection. |
| **B — Apache-2.0 after the same dependency review** | Explicit patent grant and contributor terms may be worth the longer compliance process. [ASF text](https://www.apache.org/licenses/LICENSE-2.0). | Resolve PyMuPDF as above; account for Apache `NOTICE`/change notices and all dependency obligations; then add the exact license and metadata. |
| **C — AGPL-3.0 for the application, subject to qualified review** | Reciprocity for modified network services may align with the public-good goal and PyMuPDF's published open-source path. | Review combined-work compatibility, network source-offer obligations, contributor ownership, distribution/build artifacts and whether this policy fits desired integrations. Do not assume choosing AGPL automatically satisfies every dependency or source-data term. |

**Owner to record:** selected path and license identifier; copyright holder/year; whether PyMuPDF is replaced, commercially licensed, or retained under a reviewed AGPL path; who completed dependency/notice review. Until then the README's “open-source” description is aspirational and no reuse rights should be advertised as selected. God's Eye View's MIT license does not license this code or any input dataset.

## 2. Source-use and public output decisions

The [inventory](O04-source-use-inventory.md) ties proposed decisions to current source keys. For each row, the owner must record an exact version/use decision with evidence and sign-off. A general “public data” answer is insufficient because private audit storage, record-level display, simplified geometry tiles and bulk export are different uses.

| Decision | Recommended provisional release posture | Exact owner choice / proof needed |
| --- | --- | --- |
| City development feeds `huntsville_new_subdivisions`, `huntsville_building_permits`, `madison_county_subdivisions` | Keep raw/full geometry private; do not enable new public tiles or bulk export. Check current record-level display against applicable terms before public hosting. | Determine how [City Data Depot terms](https://www.huntsvilleal.gov/development/building-construction/gis/data-depot/) apply to REST-derived records/geometry and the county-labeled city-hosted layer. Record permission/interpretation and attribution or select independently sourced alternatives. |
| D01 CityLimits scope boundary | Keep full and derived boundary internal for reconciliation; geometry review is not permission. | Approve only private scope use or establish evidence for public boundary display/tiles/export. Record the final D01 source checksum, scope ID and retention. |
| `huntsville_fema_1pct_floodplain`, `huntsville_usfws_wetlands` | Shadow storage only. Do not activate public city-mirror tiles/export. FEMA's copied import also has rejected geometry; wetlands' coverage is unknown. | Either obtain source-specific city-mirror clearance, or use a directly acquired current FEMA NFHL / USFWS NWI source with its own terms, dataset/version metadata and attribution. Revalidate completeness and derivative quality before display. |
| `huntsville_planning_agendas` | Keep full PDFs/extracted text private; reviewer-approved facts link to the source document. | Decide excerpt/attachment reuse, acceptable public fields and raw/text retention from the actual agenda archive/document terms. |
| User-submitted records and watch areas | Keep contact data, watch geometry and reviewer staging private. Publish only reviewed content with low-confidence/provenance labels. | Select data retention/deletion, notice/consent text, reviewer access, and public address/parcel policy. |

**Implementation gate:** O04 documentation alone cannot withhold an endpoint. `GET /api/environmental-overlays` currently serves full legacy geometry without a source-use check; public development record and GeoJSON routes also serve coordinates. Before hosting live data, close or gate the legacy route and verify every public map/API/export/cache path against an explicit per-source, per-use and per-version allowlist (`unresolved` defaults to withheld). A rejected public tile request must not fall back to a bulk JSON download. Retain reviewer diagnostics behind reviewer access, purge/expire previously exposed cached versions where relevant, and test both permission-present and permission-absent states. Keep demo fixtures clearly labeled as demo.

## 3. Basemap provider: owner choice required

**Current implementation:** `DevelopmentMap.tsx` uses a local background color; it requests no street/place basemap, and the map's attribution reads “Seed data for planning MVP.” Environmental catalog controls are disabled pending tile rendering. A proposed provider must not be described as already running.

**Proposed U02 option:** configurable OpenFreeMap Liberty style, with no embedded secret token or account prerequisite according to [OpenFreeMap's current service page](https://openfreemap.org/). Its [Terms](https://openfreemap.org/tos/) were updated 2026-09-09 and checked 2026-09-24: public service is as-is, has no SLA, prohibits unauthorized automated collection, and uses Cloudflare/CDN request handling under its [privacy policy](https://openfreemap.org/privacy/). OpenFreeMap requires attribution to OpenMapTiles and OpenStreetMap; [OSM's separate data license/attribution](https://www.openstreetmap.org/copyright) applies. The owner must accept the actual hosted terms, choose any budget/service fallback, and have U02 visually confirm attribution in desktop/mobile UI. No hosted tiles should be bulk prefetched or archived. The [OSMF standard tile servers](https://operations.osmfoundation.org/policies/tiles/) are **not** an automatic production fallback.

**No-provider state:** Keep the application-colored background, records, source links and controls usable. If a selected style or its tiles fail, show “Street map unavailable; development records remain available” and retain provider/source attribution for whatever data is still displayed. Do not imply that an empty background proves no roads or environmental features.

**Owner to record:** `none for alpha` or exact provider/style URL; terms accepted by whom/date; required visible attribution; browser-to-provider privacy notice; availability/budget/account assumptions; outage behavior. `none` is a valid explicit choice, but the current no-basemap UX remains a usability limitation.

## 4. Plain-language copy ready for product review

Use these texts only where the corresponding status/value is actually available. They do not replace fixing a known data or permission defect.

| Situation | Proposed text |
| --- | --- |
| Demo mode | “Demo data for testing. It does not describe current Huntsville activity.” |
| Complete scoped source | “Checked through {checked_at} for {scope_name}. All expected source IDs in that scope were retrieved and accepted. Areas outside this scope are not covered.” Show source and version. |
| Partial / failed / unknown source | “This source is {coverage_status} for {scope_name} as of {checked_at}. Some records may be missing. An empty map area does not show that no development or environmental feature exists.” Show last successful time separately from latest failed attempt. |
| Geometry confidence | “Map position may be approximate. A permit point or agenda location is not a property boundary or development footprint. Open the source record before relying on location.” |
| Flood/wetland context | “Mapped floodplain and wetland layers are screening context. They may be incomplete or out of date and are not flood-insurance, engineering, ecological or jurisdictional determinations.” Link agency sources and dates. Do not show a specific layer until its source-use and data-quality gates pass. |
| Public submissions | “Submitted information is reviewed before publication. A map location may be approximate and does not establish agency approval.” Provide a private contact/retention notice before accepting user data. |
| No basemap/provider outage | “Street map unavailable; development records remain available.” |

The current API's `DevelopmentRecord.source_fields` serializer applies `public_source_fields()` to a scalar allowlist, and geometry serialization strips extra geometry members. That is not a complete privacy clearance: `address`, `parcel_ids`, `description`, `title`, `source_url` and geometry remain separately public model fields. Review real responses and exports for applicant/owner/contractor/contact data, exact residential addresses, secret-bearing URLs and reviewer-only excerpts; decide whether address/parcel precision is necessary. Watch-area email and geometry are retained for alerts and should have a defined private retention/deletion policy. Confirm notices against actual API behavior, including demo/live mode, rather than promising that every private value is hashed or omitted.

## 5. Owner sign-off and verification still open

Before merging an implementation that claims O04 complete, record the selected values and reviewer/date here or in a linked decision record:

1. Code-license path, copyright owner/year, PyMuPDF resolution and completed dependency/notice review.
2. A separate storage, record-display, public-tile and bulk-export decision for each inventory source/version, with exact terms/permission evidence and retention; confirm city-versus-federal mirror lineage.
3. Basemap provider/style or explicit `none`, terms/privacy/attribution acceptance, and tested outage behavior.
4. Public address/parcel and submission/watch-area retention/notice policy.
5. A live API/browser verification that rights gates, privacy allowlist, source/date/coverage copy and attribution match the selected decisions. In particular, exercise `/api/environmental-overlays` and any cached tile/export path.

This documentation-only draft changes no runtime behavior. Its source IDs, boundary scope and coverage claims were reconciled against merged D01. The concrete owner decisions and runtime rights gates remain open. No upstream dataset was fetched, no provider account was created, and no root license was selected.
