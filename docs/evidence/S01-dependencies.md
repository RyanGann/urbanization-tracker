# S01 dependency update evidence

Base: `dbdaf099f31bc0444fe202aaf2ee65b3c9268d34`  
Implementation: `9bd5b2da59ac890e5d2273de50d0a75c7d5a8e02`  
Evidence run: September 19, 2026, Windows, Node 20 host and Node 22.23.2 supported runtime.

## Resolved versions and advisory disposition

| Package | Before | Resolved | Reason |
| --- | ---: | ---: | --- |
| `maplibre-gl` | 4.7.1 | 6.10.0 | GHSA-jrc7-96c5-q579 affects `<=6.4.0`; 6.4.1 is the first patched release and 6.10.0 is the current supported release checked on this date. |
| `react-router-dom` / `react-router` | 6.30.3 | 7.18.4 | The current v6 patch, 6.30.6, fixes GHSA-jjmj-jmhj-qwj2 but remains below 7.18.0 for GHSA-wrjc-x8rr-h8h6 and GHSA-337j-9hxr-rhxg. |

The production audit before the update reported one critical MapLibre advisory and three moderate router advisories. The audit after the update reports zero production vulnerabilities. Maintainer references: [MapLibre GHSA-jrc7-96c5-q579](https://github.com/advisories/GHSA-jrc7-96c5-q579), [React Router GHSA-wrjc-x8rr-h8h6](https://github.com/advisories/GHSA-wrjc-x8rr-h8h6), [React Router GHSA-337j-9hxr-rhxg](https://github.com/advisories/GHSA-337j-9hxr-rhxg), and [React Router GHSA-jjmj-jmhj-qwj2](https://github.com/advisories/GHSA-jjmj-jmhj-qwj2).

MapLibre v6 is ESM-only, so `DevelopmentMap.tsx` uses a namespace import and the documented Vite `maplibre-gl-worker.mjs?worker&url` plus `setWorkerUrl` setup. The root Node engine and Render static build runtime are pinned to Node 22 because the resolved MapLibre style-spec dependency requires Node 22. The map inspection hook remains DEV-only; the production build and production browser check expose no map global.

The browser check also found that MapLibre's `.maplibregl-map` rule overrode the earlier map container sizing rule, leaving the map parent at zero height in the production preview. The scoped `.map-stage > .map-canvas` rule restores the intended full-height interactive canvas without changing map behavior or route splitting.

## Bundle measurements

Both builds used `npm ci` and `npm run build:web` from clean worktrees with the same Vite configuration.

| Artifact | Baseline | Updated | Change |
| --- | ---: | ---: | ---: |
| MapPage JS | 814.40 kB / 221.67 kB gzip | 1,045.56 kB / 285.44 kB gzip | +231.16 kB / +63.77 kB gzip |
| index JS | 197.37 kB / 63.98 kB gzip | 212.65 kB / 69.35 kB gzip | +15.28 kB / +5.37 kB gzip |
| MapLibre worker JS | absent | 509.18 kB | new self-contained worker asset |
| MapPage CSS | 65.48 kB / 9.22 kB gzip | 83.06 kB / 10.52 kB gzip | +17.58 kB / +1.30 kB gzip |

The larger map chunk is the expected MapLibre v4-to-v6 dependency change. Route-level lazy page chunks remain present.

## Commands and results

- `npm ci` — passed on the S01 worktree; Node 20 emitted the expected engine warning, so the supported-runtime check was repeated under Node 22.
- `npm audit --omit=dev --json` — passed with `total: 0` production vulnerabilities after the update.
- `npm run typecheck:web` — passed.
- `npm run test:web` — passed, 1 file / 4 tests.
- `npm run build:web` — passed; Vite transformed 1,649 modules and emitted the worker asset.
- `node --version` — `v22.23.2` in the supported-runtime check.
- `npm ci --ignore-scripts`, `npm run typecheck:web`, `npm run test:web`, and `npm run build:web` — passed under Node `v22.23.2`; 4 unit tests passed and the build completed.
- `npm --workspace apps/web run e2e -- --workers=1` — passed, 3 mocked Chromium tests. The map test retained unsafe attribution markup checks, legitimate attribution, route remount, point selection, and polygon selection.
- `npm --workspace apps/web run e2e:production` — passed, 1 normal production-preview Chromium test in 7.7 seconds. It observed a 200 worker response, confirmed the production map hook was absent, physically clicked the post-transition canvas center for a point and a separated polygon, and verified each popup and selected detail panel.
- `git diff --check` — passed.

Production-preview browser artifacts:

- Screenshot: `apps/web/test-results/production-preview/production-preview-product-4a48d-dered-map-point-and-polygon-chromium/production-map-selected.png`
- Trace: `apps/web/test-results/production-preview/production-preview-product-4a48d-dered-map-point-and-polygon-chromium/trace.zip`

The existing Chromium fixture also injects consecutive unsafe attribution attributes (`onload` and `ontoggle`), verifies they are removed while the legitimate `Example source` link remains, and checks selection and popup behavior after navigating away and back to the map.

The final production screenshot shows the rendered point, polygon, popup, navigation control, attribution, and selected polygon detail panel after the physical pointer checks.

## Unrun or externally owned checks

The GitHub PR/CI run, full T01 integration harness, and production deployment were not run in this worktree. No live basemap or external source was contacted; map data and attribution inputs are local Playwright fixtures. Publication and CI are owned by the lead agent.
