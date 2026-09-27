# Account-required processing: edge boundary

Status: implemented and verified locally; **not deployed**. This gate depends on
the canonical profile/API changes and must ship in the same reviewed release.

The owner requires an authenticated AC account with a completed contact profile
before an audio upload or analysis starts. The released application Caddy routes
now make a body-free GET to `/v1/me/sales-xray-profile/write-eligibility` before
forwarding a new acquisition session, source upload, quote, approval, plan,
analysis or run request. The API resolves the actual session/account/profile;
the proxy does not trust client-supplied person identifiers or copy identity
headers from the preflight response. Application and worker authorization remain
required even after this edge check.

Both environment routes cover Sales Xray, learner and the API/admin/coach hosts
that can reach the API. The legacy application alias still returns its existing
410 migration response. Existing report/source reads, explicit account claims,
privacy deletion, auth and profile completion keep their own authorization.
Foundation bootstrap and release-hold routes remain unchanged.

The preflight grants continuation only on exactly HTTP 204. Unexpected 200 HTML,
202 or 206 responses fail closed with 502. Other errors are returned unchanged.
This uses Caddy's expanded forward-auth form rather than its default all-2xx
success matcher. The preflight URI explicitly clears the original query. Its original method and
URI are supplied through Caddy's standard forwarded headers; the original body
is sent only after eligibility succeeds. See the official
[Caddy forward-auth behavior](https://caddyserver.com/docs/caddyfile/directives/forward_auth).

## Local evidence

- `tests/infra/test_sales_xray_account_edge.py`: 94 HTTP checks through a real
  Caddy process, using the checked-in environment route bytes and a local
  instrumented API substitute. Thirteen processing paths are exercised for
  anonymous and ready accounts, with all five API hostnames, incomplete profile,
  unavailable preflight, slash/query handling, and preserved operations.
- A raw HTTP request announces an eight MiB source with `Expect: 100-continue`
  but sends no body. The edge returns 401 immediately; the upstream records only
  the eligibility GET with zero body bytes. A permitted request forwards the
  original synthetic bytes, method and URI exactly once.
- Combined edge and application-release infrastructure suite: 189 passed, one
  existing Linux Docker route-selector mount test skipped on this Windows host.
- Ruff and `git diff --check` pass. Full application Caddy configuration adapts
  successfully with the real parser.
- Local Caddy v2.11.4 is from the official vendor release. ZIP SHA-256:
  `1708333f79e274c7697285afe6d592ab39314e0b131e9ec6bea08ad27df62ebf`;
  executable SHA-256:
  `5cb9ab71e5756ce72840b8234177a2f40c8b4ab47a806b8e841e2b784e9df62b`.
  Linux CI extracts Caddy from the repository's digest-pinned foundation image,
  without starting that temporary container. Missing Caddy is a CI failure.

These are proxy-boundary checks, not proof of real sessions, database races,
account eligibility, provider gating, Linux deployment or production acceptance.
Those checks must pass against the integrated release before activation. No
provider call, customer upload, credential or production modification was used.
