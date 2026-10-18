# Consent wording v2: "Authority Closers account"

## Decision

On 17 Oct 2026 the owner approved changing "for my learner account" in the sign-in
consent, then delegated the choice of how ("DOne you do this on your own no issue").
The orchestrator chose a new consent version rather than a Sales Xray-only edit: the
sentence is the text of a consent version shared by Sales Xray and the learner app,
and accept events store only the version, so one product could not change it alone.
The words use the screens' own term, which reads correctly in both products.

## What changed (version `ac-learner-terms-privacy-2026-10-18-v2`, effective 18 October 2026)

- The acknowledgement now ends "...for my Authority Closers account." Nothing else in
  the sentence, its links or the checkbox behaviour changed.
- The Terms and Privacy bodies (`LEARNER_TERMS`, `LEARNER_PRIVACY`) and the learner
  registration checkbox copy are byte-identical to v1; only the version id and the
  effective date moved in `apps/learner-web/app/lib/learner-policy.ts`.
- One registry of words per version: `packages/python/ac_platform/identity/learner_consent.py`.
  The back end consent document (`GET /v1/me/consent`, shown by the learner renewal
  screen) reads it. The Sales Xray sign-in (`account-auth.tsx`) holds the same words;
  a test pins them to the registry.
- The release profiles (`staging.env`, `production.env`) and the installer's reviewed
  literal pin v2. The installer test refuses v1, the 13 September version, the dev
  placeholder and anything unreviewed.

## v1 stays recoverable

The words accepted under `ac-learner-terms-privacy-2026-09-30-v1` are kept verbatim in
the registry (a test pins them byte for byte) and, with the whole v1 policy copy, in git
at the commit before this change. Earlier accept events are not rewritten: a renewal
appends a new `identity.learner_consent_accepted.v1` event with
`previous_consent_version`, and the person row stays only the current projection
(`tests/unit/http/test_learner_consent_routes.py` checks the v1 event is untouched).

## Who is asked again

- Learner app users: the consent renewal screen, with the v2 words, before course access.
- Sales Xray users who sign in with Google: the existing supersession on sign-in records v2
  and keeps the v1 event.
- Not asked by this change: Sales Xray users who sign in with an email code or a password.
  By the identity design an email-code sign-in does not rewrite the consent of an already
  verified account, and Sales Xray has no renewal screen of its own. They keep their v1
  record, which is valid. Closing that needs a Sales Xray renewal screen on `/me/consent`.
- A first-time sign-up code requested before the release and entered after it is refused
  (that code carries v1); the person asks for a new code. A sign-in page left open
  re-reads the version on failure and asks for the box to be ticked again.

## Checks

See the commit message for the exact test runs.
