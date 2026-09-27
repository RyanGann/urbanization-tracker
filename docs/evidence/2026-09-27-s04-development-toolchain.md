# S04 development toolchain evidence — September 27, 2026

Base: merged main `45660337b49b71c3daff0d88d3c36066c4abf816`. The C04 inspection reported ten affected package entries: one low, four moderate, four high, one critical. Every installed path in that report was marked `dev: true`. This classification does not establish exploitability or an incident.

The runtime libraries patched in S01 retain their exact locked versions and integrity values. Only the direct Vite/Vitest declarations change. npm deduplication consolidates Vite at 6.4.3, avoids an unnecessary Vite 8 installation, and removes the old vite-node chain. Vitest 4.1.11 is necessary for the mocker fix as well as the older UI advisory; the existing test command runs without the UI server. Vite 6.4.3 includes the Windows development-server fix.

| Package | Previous lock | New lock | Advisory disposition |
| --- | --- | --- | --- |
| vite | 5.4.21 | 6.4.3 | Above the reported affected 6.4.2 boundary |
| vitest | 2.1.9 | 4.1.11 | Above UI and mocker affected ranges |
| @vitest/mocker | 2.1.9 | 4.1.11 | Patched redirect mock traversal |
| @babel/core | 7.29.0 | 7.29.7 | Above reported affected boundary |
| baseline-browser-mapping | 2.10.31 | 2.11.26 | Above reported affected boundary |
| browserslist | 4.28.2 | 4.29.1 | Above reported affected boundary |
| esbuild | 0.21.5 | 0.25.12 | Above reported affected boundary |
| nanoid | 3.3.12 | 3.3.19 | Above reported affected boundary |
| postcss | 8.5.15 | 8.5.28 | Above reported affected boundary |
| vite-node | 2.1.9 | Removed | Old inherited Vite chain removed |

Previous versions were independently read from the base lockfile; the originating audit records affected ranges rather than every resolved version.

Primary advisories consulted: [Vite Windows deny bypass](https://github.com/vitejs/vite/security/advisories/GHSA-fx2h-pf6j-xcff), [Vitest mocker traversal](https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9), [Vitest UI execution](https://github.com/vitest-dev/vitest/security/advisories/GHSA-5xrq-8626-4rwp), [Babel source maps](https://github.com/advisories/GHSA-4x5r-pxfx-6jf8), [baseline mapping](https://github.com/advisories/GHSA-w5vr-8v7q-w6rv), [Browserslist memory](https://github.com/advisories/GHSA-c83g-rgw3-j3cx), [Browserslist stats](https://github.com/advisories/GHSA-73wf-gq98-2v4g), [esbuild server](https://github.com/advisories/GHSA-67mh-4wv8-2f99), [nanoid zero size](https://github.com/advisories/GHSA-2v37-7h3g-55p8), and [PostCSS source maps](https://github.com/advisories/GHSA-fxqj-rqcc-2cmp).

## Local validation

The isolated lockfile update used official npm 11.6.2 through npm exec: install/update/dedupe with `--package-lock-only --ignore-scripts --no-audit --no-fund`. npm 10.9.8 failed resolution with `Cannot read properties of null (reading edgesOut)`; no failed lockfile was retained. A separate disposable Node 22 container installed the resulting lockfile with npm 10.9.8 successfully.

Node 22 clean-directory validation passed: `npm ci --no-audit --no-fund`, `npm run typecheck:web`, `npm run test:web` (six tests), and `npm run build:web`. A base/new lockfile comparison found zero production version or integrity changes. The build retains the existing large MapLibre route chunk warning; this security follow-up does not satisfy the performance budget.

Existing development/production and real API browser smoke are required CI checks; their results will be linked after completion. No local live-browser validation is claimed here.

## Audit limitation

The post-change versions were compared with the already captured audit and maintainer advisories. A fresh registry audit was not run: automatic approval review rejected transmitting the lockfile metadata to the registry. Installs and resolution used `--no-audit`. This report does not claim a zero-vulnerability audit or prove every dependency free of newly published issues.
