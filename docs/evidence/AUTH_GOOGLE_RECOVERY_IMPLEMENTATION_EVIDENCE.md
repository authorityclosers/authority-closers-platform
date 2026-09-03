# Google learner recovery implementation evidence

Status: local and immutable staging runtime verified on exact release
`81635d18569c06962af37c1fa64d0d5814d0f2bf`.

## Problem closed by this change

The learner Google authentication callback previously returned a raw RFC 7807
response when a recognized provider identity did not yet have the exact active
learner consent. That response was technically fail-closed but was not an
acceptable browser journey.

The callback now keeps malformed or hostile transactions fail-closed while
turning valid learner callback failures into fixed, same-origin recovery
results:

- `consent_required` for a recognized learner identity with no recorded
  consent;
- `consent_update_required` for a different recorded consent version that
  cannot be silently overwritten;
- `registration_required` for a verified Google identity that is not linked to
  a learner;
- `provider_rejected` and `provider_unavailable` for bounded Google callback
  failures.

Every recovery redirect deletes the one-time OAuth transaction cookie and adds
`Cache-Control: no-store`. Database failures leave the provider transaction,
session, identity audit fields, and learner membership unchanged because the
recovery response is emitted only after transaction rollback.

## Controlled UI grounding

- Drive source: `AUTH-01-desktop-registration.png`
  (`1K9qpP-OTsgyuhJ3mtmZYDj2-7EFv_MJb`).
- The implemented callback reuses the same full-height Clarity Grid split,
  approved lake asset, type scale, card, button, and mobile auth header as the
  registration, verification, and recovery family.
- No provider payload, authorization code, token, email address, or internal
  error detail is rendered in the browser result.

Local comparison captures:

- `docs/evidence/screenshots/v0.1-auth-recovery-local/google-consent-recovery-desktop-1488x1058.png`
- `docs/evidence/screenshots/v0.1-auth-recovery-local/google-consent-recovery-mobile-390x844.png`

The mobile capture was measured at `390px` viewport width with `390px`
document scroll width and exactly one `h1`; no horizontal overflow was present.

Live exact-release captures:

- [`v0.1-staging-exact-81635d1/README.md`](screenshots/v0.1-staging-exact-81635d1/README.md)
- login, registration, Google consent recovery, forgot-password,
  verification empty-token, and reset empty-token states at desktop and
  mobile widths (12 images total).

## Verification executed

```text
pnpm --filter @ac/learner-web lint
pnpm --filter @ac/learner-web typecheck
pnpm --filter @ac/learner-web test -- app/lib/learner-ui.test.ts
uv run ruff check packages/python/ac_platform/http/auth.py packages/python/ac_platform/tenancy/learner_provisioning.py tests/unit/http/test_auth_routes.py tests/integration/test_password_identity_http_postgresql.py
uv run pytest tests/unit/http/test_auth_routes.py -q
$env:AC_TEST_DATABASE_URL='postgresql+psycopg://ac_owner:local-owner-only@127.0.0.1:5432/ac_platform'; uv run pytest tests/integration/test_password_identity_http_postgresql.py -q
```

Observed results:

- learner UI: `33 passed`;
- identity route unit suite: `34 passed`;
- fresh-PostgreSQL password/Google identity suite: `7 passed`;
- complete local validation: `836 passed`, `97 skipped`; skipped database
  suites were then supplemented by the configured seven-test PostgreSQL suite
  above, and the skipped Playwright package was supplemented by the in-app
  browser desktop/mobile checks;
- frontend lint, frontend typecheck, Python Ruff: passed;
- local browser: desktop and mobile consent-recovery routes rendered with the
  expected action and no raw JSON.
- independent security/code rereview: approved after consent conflicts and
  unlinked-provider recovery were narrowed to dedicated exception types; a
  dangling person link and provider-key ownership collision remain fail-closed.

## Exact-release CI and staging runtime evidence

- reviewed commit:
  `81635d18569c06962af37c1fa64d0d5814d0f2bf`;
- pull-request application validation: GitHub Actions run `33460969038`,
  passed;
- pull-request control-plane validation: GitHub Actions run `33460969014`,
  passed;
- workflow-dispatch validation and immutable image packaging: GitHub Actions
  run `33461232992`, passed;
- immutable deployment command:
  `pwsh -NoProfile -File .\scripts\Deploy-Staging.ps1 -ReleaseSha 81635d18569c06962af37c1fa64d0d5814d0f2bf`;
- archive path-safety, commit binding, image/release identity, migration,
  container health, learner/PWA assets, API live/ready/catalog, protected
  admin route, WordPress boundary, and Google OAuth start/callback binding:
  passed;
- direct live callback result
  `/auth/callback?result=consent_required`: rendered the recovery UI at desktop
  and mobile widths with no RFC 7807 body, request ID, provider payload, token,
  or horizontal overflow;
- registration Google button: disabled before exact consent and enabled after
  the checkbox is checked;
- post-cutover recovery request: accepted, with a fresh message delivered from
  `Authority Closers <learn@authorityclosers.com>` to
  `admin@authorityclosers.com` at `2026-09-01T02:23:32Z`.

The user-specific Google account-selection and final provider callback were not
replayed after this deployment because selecting the signed-in Google account
transmits provider identity data and requires action-time user confirmation.
The start/callback boundary and recovery behavior are exact-release smoke,
integration, and browser-proven; a final real-account re-consent completion is
still an explicit runtime gate. Production remains a separate release decision.
