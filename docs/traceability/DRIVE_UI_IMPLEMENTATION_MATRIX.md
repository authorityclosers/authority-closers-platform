# Drive UI implementation matrix

Status: candidate audit, 2026-09-04. This matrix is keyed by exact Drive file
ID. It distinguishes the selected v0.1 implementation from future product
references; a visual reference is not evidence that the capability exists.

The current candidate is represented by exact release
`5c7333c5a588f5209acd5ca9b5ce0e03e20e16a4`, with bounded controller smoke and
an authenticated `/learning` accessibility-tree observation recorded in
[EVD-005](../knowledge/v0.1-alpha/EVD-005-exact-staging-5c7333c5.md).
Existing screenshot evidence remains scoped to exact release `27fafae` for the
full learner journey and exact release `81635d1` for the later auth/recovery
family; neither pack proves the current candidate's visual or capability delta.

The controlled Drive package selects **Clarity Grid**. `Study OS` and `Signal
Path` are deliberate reserves. The package README also says the images are
high-fidelity references rather than production behavior, so runtime state,
authorization, tenancy, recovery, and provider evidence remain authoritative.

Status meanings:

- `candidate` — implemented in the current reviewed local candidate; live
  exact-SHA verification is still required.
- `staging-proven` — implemented and captured from the named immutable staging
  release; production remains a separate gate.
- `partial` — the v0.1 contract/surface exists, but the named visual includes a
  provider, seeded state, or breadth that is not yet runtime-proven.
- `extension` — intentionally not part of the approved v0.1 boundary.
- `reserve` — visual exploration, not an implementation target.

## Visual direction

| Drive asset                                                          | Status    | v0.1 treatment                                                           |
| -------------------------------------------------------------------- | --------- | ------------------------------------------------------------------------ |
| `DIRECTION-A-Clarity-Grid.png` (`1VOgXqLvaslXPwYM8bzqboUVQe-JYdT39`) | candidate | Selected visual system for learner, auth, onboarding, admin, and studio. |
| `DIRECTION-B-Study-OS.png` (`1GsBl_IUL_Kbh8cWCsVfUk5oamy9PxCt8`)     | reserve   | Retained by Drive as an editorial-learning reserve.                      |
| `DIRECTION-C-Signal-Path.png` (`1A8cFVEs8n9yfj9g71PCPj8L9Ac0YF0MS`)  | reserve   | Retained by Drive as a practice/analytics reserve.                       |

## D01 — platform shell and navigation

| Drive asset                                                                  | Status    | v0.1 treatment                                                                                                     |
| ---------------------------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------ |
| `SHELL-01-desktop-home.png` (`1JrHdP23rz27ECr2rVPDpRi_GSYMWaKEC`)            | candidate | Desktop learner rail, header, API-backed home, and active Progress/Settings navigation; Library remains disabled.  |
| `SHELL-02-mobile-home.png` (`12lQfy7L305LLoBw1VcLulz5gYxI9AM7t`)             | candidate | Responsive learner header and safe-area bottom navigation, including candidate `/progress` and `/settings` routes. |
| `SEARCH-01-desktop-command-search.png` (`1fIOdGNwwSRx30ba2dRSCsBv1XWguZ01X`) | extension | Search remains visibly disabled; library discovery and permission-aware command search are not claimed.            |

## D02 — auth and onboarding

| Drive asset                                                              | Status         | v0.1 treatment                                                                                                                                                                                                                         |
| ------------------------------------------------------------------------ | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AUTH-01-desktop-registration.png` (`1K9qpP-OTsgyuhJ3mtmZYDj2-7EFv_MJb`) | staging-proven | Full-height split registration composition, explicit 18+/Terms/Privacy consent, password-manager fields, consent-gated Google registration, and desktop/mobile staging captures are verified on release `81635d1`.                     |
| `AUTH-02-desktop-verification.png` (`1NLx4nRVxS_5bsu9hOMjEHW5Yb25GwNr5`) | staging-proven | Verification/recovery visual family, Google callback recovery, branded responsive verification/reset/welcome email renderers, desktop/mobile live captures, and post-cutover recovery-mail delivery are verified on release `81635d1`. |
| `ONB-01-desktop-context.png` (`1-iZ5l-57RezRmFYyXcyY45jWiIFTF0um`)       | candidate      | Three-step progressive onboarding inside the learner workspace shell.                                                                                                                                                                  |
| `ONB-02-mobile-context.png` (`1ewm-HXQZv10tkfq3UNvly4JWHeIAFOWT`)        | candidate      | Mobile onboarding composition with skip/save behavior and session-expiry recovery.                                                                                                                                                     |

The candidate also adds login, forgot/reset password, offline, canonical
`/session-expired`, and allowlisted Google callback recovery screens in the
same visual family. These are required contracts even though the reference
folder does not contain a separate image for every state.

## D03 — learner home and library

| Drive asset                                                          | Status    | v0.1 treatment                                                                                                                                                                                |
| -------------------------------------------------------------------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `HOME-01-mobile-dashboard.png` (`1CgJ3XhYcclRxj2Zb6HRUXnH6pcQEcu01`) | candidate | Exact release `27fafae` proves the older API-backed enrolled home. The candidate adds onboarding gating and connected consent-backed `Start free course`; exact-SHA staging proof is pending. |
| `LIB-01-desktop-library.png` (`1aDOi1nnq2lLOepsAGXIngkGmBtB1lp5q`)   | extension | Broad library discovery, filters, bookmarks, and recommendations are not part of the first slice.                                                                                             |
| `LIB-02-mobile-library.png` (`1kwrBVOdPm637iqrknWEO79RQzUZM6DGi`)    | extension | Mobile library breadth follows the same explicit extension contract.                                                                                                                          |

## D04 — course and content player

| Drive asset                                                            | Status    | v0.1 treatment                                                                                                                                            |
| ---------------------------------------------------------------------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `COURSE-01-desktop-overview.png` (`1sQs7ew-v1IO-Xb4h87dV_LOqFYRtloRk`) | candidate | API-backed published overview and version-pinned four-module path; Modules 2–4 remain activity-empty extension topology.                                  |
| `COURSE-02-mobile-outline.png` (`1vp7jaZ_LUl6Glm1NzljgFxIK8nB8rfs8`)   | candidate | Responsive server-derived module outline and lock reasons; no local two-module fixture is used by the route runtime.                                      |
| `PLAYER-01-desktop-player.png` (`1BASW-gVdQR8lWxDRfXN_svY5yqXkez-u`)   | partial   | Candidate activity UI connects draft and authorized evidence submission. Approved media, transcript, playback, and reviewer runtime proof remain pending. |

## D05 — practice, review, progress, and certificates

| Drive asset                                                               | Status    | v0.1 treatment                                                                                                                                                     |
| ------------------------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `ACT-01-desktop-quiz.png` (`1vubxTMRoavtCMi7S-BglxOX05HKoEIwl`)           | extension | Quiz is not in the approved Module 1 sequence.                                                                                                                     |
| `ACT-02-mobile-reflection.png` (`1QMLN1QAlFDVnqlCG8JMWjG3OcEbo85ua`)      | partial   | Exact release `27fafae` proves server draft restore. Candidate UI also submits evidence only when the API authorizes it; exact-candidate runtime proof is pending. |
| `ACT-03-desktop-implementation.png` (`1B03Slo9QX3c4vrE552cEtlqnDitVbnaO`) | partial   | Candidate implementation-evidence form is API-connected; no exact-SHA mutation proof, media upload, or external-review breadth is claimed.                         |
| `REVIEW-01-mobile-feedback.png` (`16HO9FeftBfm6uW334UWrAWYUyhC4YIwW`)     | partial   | Append-only review domain/routes exist, but reviewer assignment/UI and human feedback runtime remain unconnected and unfabricated.                                 |
| `PROG-01-desktop-progress.png` (`1HV9Ea2xn72e9s9pZ8UkAuc5bt4mVZ4yj`)      | candidate | `/progress` renders canonical projection counts, module activities, locks, no-enrollment, retry, and 401 recovery; exact-SHA staging proof is pending.             |
| `CERT-01-mobile-certificate.png` (`1jB15DjmbsZJ3ZTa9Pg1rnYj8a_G-PiLt`)    | partial   | Candidate self-scoped certificate read is API-backed, but authoritative issuance and end-to-end staging proof remain partial.                                      |

## D06 — organization admin and analytics

| Drive asset                                                                      | Status    | v0.1 treatment                                                                                          |
| -------------------------------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------------------- |
| `ORG-01-desktop-overview.png` (`1x--v5pwj4GkCnhqodkSRZfIeLNxXaEjR`)              | candidate | Separate admin shell with verified-session tenant context and truthful unknown metrics.                 |
| `ORG-02-desktop-people-assignment.png` (`1dTc6MsylnEvS0a_nIDR9PiL259QLpuF1`)     | partial   | People/assignment surface is present and fail-closed; no learner directory or assignment is fabricated. |
| `REPORT-01-desktop-learning-analytics.png` (`1uOsRt03FUNlegDW2bFiIKQwjWdXh5MkK`) | extension | Broad reporting, filters, exports, and tenant analytics are not part of v0.1.                           |

## D07 — author studio and media

| Drive asset                                                                   | Status    | v0.1 treatment                                                                                        |
| ----------------------------------------------------------------------------- | --------- | ----------------------------------------------------------------------------------------------------- |
| `AUTHOR-01-desktop-course-outline.png` (`1SNPUHW-TvhMb82bxqQh7zZMK9YmEi8yf`)  | partial   | Separate studio foundation and immutable outline preview exist; unsafe publish actions remain locked. |
| `AUTHOR-02-desktop-activity-editor.png` (`1HmQ5yuyQg8Jkey32IKZo37Wwk1X9p3-P`) | extension | Full activity authoring is an extension contract.                                                     |
| `MEDIA-01-desktop-media-library.png` (`1sNAK4Uwnqfa550ZJEqfwQhm0MKF8Hp-z`)    | extension | Media processing/library UI is provider-gated and not claimed.                                        |

## D08 — settings, billing, and integrations

| Drive asset                                                                      | Status    | v0.1 treatment                                                                                                                                                                                                                  |
| -------------------------------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SET-01-desktop-tenant-branding.png` (`1vVHIDFKsfS64YkuYK1ojf9h384P4Qq65`)       | extension | Tenant branding UI is not part of the first slice.                                                                                                                                                                              |
| `SET-02-mobile-profile-notifications.png` (`1SmQuMR7fOYaarIJ_1HweVt0nY6ejwKPM`)  | partial   | Candidate `/settings` reads verified account/onboarding data, links profile editing, signs out, and offers Light/Dark/System as local browser presentation only. Server-synced preferences and notifications remain extensions. |
| `SAAS-01-desktop-plan-billing.png` (`1tI6pOO6sZae9ARqQDgNgHj6GBebNZqeU`)         | extension | Billing is explicitly excluded from v0.1.                                                                                                                                                                                       |
| `INT-01-desktop-integrations-identity.png` (`1lDZFd007vqdB3PyZBwPD9EbggE4M2Nbc`) | extension | SSO, SCIM, API/webhook management, and broad integrations are explicitly excluded.                                                                                                                                              |
| `COMM-01-mobile-calendar-inbox.png` (`1S0TOWyIQL31DSx7BiBiG_kcDKfHsdSQI`)        | extension | Calendar/inbox/communication breadth is not part of v0.1.                                                                                                                                                                       |

Native Windows/iOS applications remain extension contracts. The v0.1 target is
the browser/PWA surface; responsive layouts and local appearance preferences do
not constitute native-app implementation.

## Release gate

`candidate` is not equivalent to live. Promotion requires an immutable commit,
Node 24/Linux CI, exact-SHA staging deployment, API/admin/learner smoke tests,
responsive visual comparisons, and an honest handoff naming every remaining
`partial` or `extension` item. In particular, the current candidate still needs
capability-specific proof for the distinct public learner tenant, consent-backed
free enrollment, evidence submission, `/progress`, `/settings`, and local theme
behavior; the bounded exact-SHA deployment/controller smoke is already recorded.
Media playback, Modules 2–4 content, library/search, certificate issuance,
broad admin, billing, SSO/SCIM, and native apps remain partial or extension
boundaries after that proof.
