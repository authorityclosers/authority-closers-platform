# Sales Xray upload challenge policy â€” 14 September 2026

The staging and production Sales Xray document policies previously blocked the
upload verification script and iframe. The two web route policies now allow
`https://challenges.cloudflare.com` in `script-src` and `frame-src`. Existing
same-origin frames remain allowed. `connect-src 'self'` and all other directives,
headers, API policies and host routes are unchanged.

This follows the [official Turnstile CSP requirements](https://developers.cloudflare.com/turnstile/reference/content-security-policy/),
checked on 14 September 2026. The app uses the explicit Turnstile script URL.
The document is allowed to embed the challenge; its own `frame-ancestors 'none'`
and `X-Frame-Options: DENY` protections remain intact.

## Receipts

The adjacent `turnstile-csp-20260914` packet contains the receipts with portable
LF line endings and trailing whitespace removed; originals remain in the external
audit directory:

- **Before:** both Chromium cases failed against the unchanged policies because
  the challenge script could not load: 2 failed in 11.20 seconds.
- **After:** both staging and production cases passed in 16.17 seconds. A real
  loopback HTTP response carries the exact checked-in Caddy policy. Chromium
  loads a synthetic script and iframe at the approved origin, while blocking
  an unrelated script, iframe and fetch. The API deny-all policy is also checked.
- **Infrastructure:** 4 existing route, release projection, hold and log-redaction
  checks passed in 0.38 seconds; 91 unrelated cases deselected.
- **Compiled Next runtime:** HTTP 200, zero CSP headers in both the actual
  document response and compiled routes manifest. The existing account-library
  build `x5hb_5QbrL1TMz4a7t7ud` was reused after comparing 140 frontend and lockfile
  source files with this worktree. This was not a new frontend build.
- **Scope:** restoring only the two intended CSP additions reproduces both
  complete route files from base `278456864d6c7bc3be4d85ce389cb963f571902d`.
- Ruff lint and format checks passed for the new browser regression.
- Independent Luna review found no actionable issues. The release coordinator
  also reviewed the two route changes and regression before integration.

The browser substitutes the two challenge resource bodies and blocks all other
external requests. These receipts prove browser CSP enforcement, not an actual
Cloudflare challenge solve or server-side token verification. No provider calls,
recording processing, hosted mutation, new Caddy runtime adaptation, staging
deployment or production deployment occurred in this leaf.

The release owner must integrate the exact commit, build the combined release,
and verify the real hosted upload challenge and authenticated report flow.
