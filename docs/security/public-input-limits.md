# Public input limits

S02 protects `POST /api/public-submissions` and `POST /api/watch-areas`.

The API buffers at most 256 KiB before JSON decoding, counting received bytes rather than trusting Content-Length. JSON must be UTF-8 with no more than 32 container levels. Oversized requests return 413; malformed fields/geometry return 422. Error bodies contain safe messages and field names, never rejected input values.

Public geometry accepts finite two-dimensional longitude/latitude coordinates and at most 2,000 positions, including closing positions. Polygon rings must explicitly close. Watches require Polygon/MultiPolygon; tips may also use Point or null. Empty, self-intersecting, improperly nested and out-of-range geometry is rejected without repair. Polar points and polygons spanning 180° longitude are outside this pilot's geometry contract.

Live PostgreSQL mode uses PostGIS validity and WGS84 geography area, outside the canonical mutation lock. Validation failure or database unavailability never selects the local validator as a fallback. Demo/artifact mode uses isolated Shapely/pyproj validation and does not read live PostgreSQL. The default watch limit is 2,500 km²; `PUBLIC_WATCH_MAX_AREA_SQ_KM` can lower it. A submission with unknown location retains null geometry and cannot be published through direct or imported reviewer decisions. The current participation form clearly submits unknown location; U03 owns the independent location picker.

Email parsing checks syntax without DNS/network requests. Reserved `.test` addresses remain available for isolated fixtures. Source links accept http/https only and cannot contain credentials; the API does not fetch them. Watch filters accept only `statuses` and `development_types`, with the shared U00 values. An absent filter is unrestricted; an explicit empty list matches nothing.

## Shared quota configuration

Live PostgreSQL public writes require `PUBLIC_WRITE_QUOTA_SECRET` containing at least 32 UTF-8 bytes. Use a randomly generated secret and the **same value for every API worker/instance**. Missing/short secret, invalid proxy configuration or an unavailable quota database returns 503 on public writes. Read/reviewer/liveness routes remain available subject to their existing dependencies. The Render API blueprint uses `generateValue: true`; Render documents this as a randomized 256-bit value in its [Blueprint specification](https://render.com/docs/blueprint-spec).

`PUBLIC_WRITE_QUOTA_LIMIT` defaults to 10, independently for submissions and watches, per resolved client address per fixed UTC hour (range 1–1,000). Requests that decode as JSON consume quota before field/topology validation; body/JSON parse failures do not. Exhaustion returns 429 and Retry-After in seconds. Fixed windows permit a burst on either side of an hour boundary. Counters use an atomic PostgreSQL upsert shared across workers and survive API restart.

Stored keys are HMACs over the address, route and window; no raw client address is stored in this table. Including the window prevents linkage by a stable stored key across hours. Rows expire logically two hours after their window starts. Each subsequent write removes up to 100 expired rows using SKIP LOCKED; an idle service may retain expired hashes until the next write. Application rollback should retain this additive table. Dropping it resets the active quota, so downgrade is a maintenance action.

Demo/artifact mode uses an isolated process-local quota and ephemeral secret. It resets on restart and is **not a multi-worker production control**. Hosted operation requires live PostgreSQL. Ordinary integration scenarios explicitly raise the synthetic quota to 1,000 to preserve their unrelated assertions; the S02 scenario uses the actual default 10 with two workers.

## Proxy trust

Run Uvicorn with `--no-proxy-headers` (the Docker entrypoint does this). This preserves the actual transport peer for application trust decisions. Do not also let Uvicorn rewrite that peer from forwarding headers.

`PUBLIC_WRITE_TRUSTED_PROXIES` is a comma-separated list of verified proxy IP networks. Its default is empty, so X-Forwarded-For is ignored. When the immediate peer is trusted, the API walks the forwarding chain right-to-left, stopping at the first untrusted address. IPv4-mapped IPv6 normalizes to IPv4; scoped/invalid addresses cannot create arbitrary buckets. Malformed trusted-chain entries conservatively fall back to the immediate peer.

Behind a proxy, the default groups users into that proxy's quota bucket. Configure the actual ingress chain and test forged headers before opening public access. Do not use `0.0.0.0/0`, assume Render outbound ranges are ingress ranges, or infer trust from a header alone. Render confirms that applications see proxy addresses and discusses forwarded client addresses in its [edge protection guidance](https://render.com/articles/how-render-handles-ddos-attacks); its [PocketBase guidance](https://render.com/articles/host-pocketbase-on-render) also explains why a caller-controlled leftmost X-Forwarded-For entry is unsafe. This PR does not assume a provider-specific ingress CIDR or CF-Connecting-IP trust guarantee. Deployment preflight/rehearsal must verify the chosen network configuration.

## Privacy and recovery

Receipts expose only their declared public fields. Current records, map properties and version snapshots apply the shared C03 scalar source-attribute allowlist. Nested source dictionaries, contacts, private notes and tokens remain private. Public submission notes are not copied into a published description. Corrupt historical snapshots produce a safe unavailable response. Existing stored records are filtered on read; this change does not destructively clean historical data.

Rejection logs expose only fixed reason codes suitable for aggregate counts, not emails, raw bodies, coordinates, notes or tokens. Reverse-proxy access logging policy remains an operator concern; do not enable request-body or authorization-header logging. No email is sent by these controls; confirmation lifecycle limits remain S03 work.

Reproduce the isolated HTTP/PostGIS acceptance with:

```text
node scripts/run-integration.mjs --suite api --scenario input-limits
```

The runner owns a unique labelled stack, upgrades through migration `20260922_0005`, seeds synthetic data, tests quotas with 20 simultaneous clients, restarts the API, and removes only that run's resources. Never use the saved project snapshot or the preview database as a validation target.
