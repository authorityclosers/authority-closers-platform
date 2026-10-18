# Sales Xray consent renewal card (18 Oct 2026)

Follow-up to `20261018_AUTHORITY_CLOSERS_ACCOUNT_CONSENT_V2.md`. Consent v2
re-asks learner-app users (its renewal screen) and Sales Xray Google sign-ins,
but not Sales Xray email-code or password users: identity does not rewrite
consent for verified accounts and Sales Xray had no renewal screen. This adds it.

## What it does

- `apps/sales-xray-web/app/consent-renewal.tsx` (`ConsentRenewal`) is mounted once
  inside the app frame (`standalone-studio.tsx`, `AppFrame`) and inside the plans
  purchase session (`app-session.tsx`, `PurchaseSession`). Embeds are left out; the
  learner app has its own screen.
- After the account is confirmed signed in, it reads `GET /v1/me/consent`.
  `current`: renders nothing (no element, no layout shift, no extra request after
  the one read). `renewal_required` or `consent_required`: one card, fixed over the
  page, with the document's acknowledgement words (verbatim from the server), links
  to the Terms and Privacy notice (new tab), a checkbox and Accept.
- Accept sends `POST /v1/me/consent/renew` with `{accepted: true, expected_version}`
  where the version is the one the server showed. The server records it in the audit
  chain and replays a repeated acceptance. On success the card goes and the person is
  on the page they were on (it never navigates).
- Problems are corner cards (`notice-center`), never inside the card: a failed save
  (card stays ticked, Try again sends the same version), 409 version changed (the new
  words are read, the box is unticked, an info card says so), 403 (cannot accept
  here, no retry), 401 (reload), and a failed read (Try again). 401 or 403 on the
  read means signed out or an account that cannot accept here: nothing is shown.
- The card cannot be dismissed (no close X, Escape and outside presses do nothing, Tab
  stays inside). While it is open `html[data-sx-consent]` raises the corner cards
  above it (`notice-center.module.css`, one rule).
- The answer is bound to the session it was read for, so a person signing in after
  someone else never sees the earlier person's card.
- Not changed: consent words, versions, back end, identity semantics.

## Checks (ac, 18 Oct)

- vitest: `consent-renewal.test.tsx` (14: renders for renewal_required and
  consent_required, hidden for current and for signed-out without reading, accept
  sends the server version, no send until ticked, Escape, failed save + retry, lost
  connection, 409, 403, failed read, session switch), `consent-renewal-client.test.ts`
  (16), one wiring test in `standalone-studio.test.tsx` (its fetch stub now answers the
  consent read outside the recorded calls, like the logo read). Whole web suite: 252
  files passed, 3 skipped; 3139 tests passed, 8 skipped.
- prettier --check, eslint --max-warnings 0, tsc --noEmit: clean.
- pytest (consent documents, consent routes, version binding, auth and Sales Xray
  auth routes): 225 passed.
- Dev (phone harness, 390x844, light and dark): card, ticked, failed save corner card,
  Try again then accepted on the same URL, and a current account's fresh load with no
  card and layout shift 0. Card 358x395 at 390 wide; every control 44 px tall; no
  horizontal scroll. Shots and `log.txt`: `~acdev/strikes/mobile-ui/shots/2026-10-18/consent-renewal/`.

## Notes for testers and harnesses

- Dev reads its consent version from the dev back end (`staging-test-document-v1`), so
  any older test account is `renewal_required` until it accepts once. The QA smoke
  account accepted once on 18 Oct (real flow, through the card); sweeps and browser
  checks that use a different or new-era account must accept first or they meet the card.
- Shots mock the consent answer (no writes) except that one real accept.

## Not covered

- The Android app (Capacitor) was not run; the card is web-only code and shows in app
  mode (`html[data-sx-app]` hides only `.sx-web-only`). The links open a new tab, the
  same as the sign-in sentence's links.
