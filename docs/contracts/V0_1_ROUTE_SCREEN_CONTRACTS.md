# v0.1 route and screen contracts

Status: implementation candidate
Deployment status is tracked separately in
[`PLATFORM_SURFACE_STATUS.md`](../traceability/PLATFORM_SURFACE_STATUS.md).
This contract includes the current uncommitted candidate. It is not a staging
deployment claim; the candidate still requires an immutable commit and
exact-SHA staging proof.

## Learner screen contract

| Browser route                            | Authority                     | Primary states and actions                                                                                                                                          | Activation dependency                             |
| ---------------------------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `/`, `/programs/{slug}`                  | Public catalog API            | loading, honest empty, retry, API-backed published detail, explicit idempotent free-enrollment action; no local course fixture is substituted                       | approved published seed and public learner tenant |
| `/login`                                 | Identity API                  | email/password, Google, invalid credentials, verification required, recovery link                                                                                   | deployed identity database and provider evidence  |
| `/session-expired`                       | Identity API                  | explicit 401 recovery, email/password or eligible-existing-person Google reauthentication, durable-work reassurance                                                 | deployed identity database and provider evidence  |
| `/register`                              | Identity API                  | consent-gated email/password registration, password-manager autocomplete, existence-neutral acknowledgement                                                         | reviewed environment consent and email delivery   |
| `/auth/callback`                         | Identity API                  | safe Google recovery results for missing registration, missing/current consent, provider rejection, and provider outage; never displays provider payloads or tokens | valid signed OAuth transaction                    |
| `/verify-email`                          | Identity API                  | fragment-token consume, success/session, invalid/expired, existence-neutral resend                                                                                  | worker plus approved email adapter                |
| `/forgot-password`                       | Identity API                  | existence-neutral recovery acknowledgement                                                                                                                          | worker plus approved email adapter                |
| `/reset-password`                        | Identity API                  | fragment-token consume, matching new passwords, session revocation, expired/missing link                                                                            | worker plus approved email adapter                |
| `/onboarding`                            | Person profile                | loading, save/resume, revision conflict, skip, complete, retry                                                                                                      | authenticated verified person                     |
| `/home`                                  | `/v1/me`, context, catalog    | unauthenticated, empty, retry, server-owned learner context                                                                                                         | learner tenant provisioning                       |
| `/learn/{programSlug}`                   | canonical learning projection | progress, locked reasons, module path, retry                                                                                                                        | enrollment pinned to published version            |
| `/learn/{programSlug}/module/{moduleId}` | learning projection           | ordered activities and prerequisite locks                                                                                                                           | same as program path                              |
| `/activity/{activityId}`                 | activity/draft/evidence APIs  | load, offline/error, optimistic draft save, server-authorized reflection/implementation/review/improvement evidence submission, lock/permission states              | approved activity topology and evidence policy    |
| `/progress`                              | canonical learning projection | loading, session-expired, retry, no-enrollment recovery, course percentage/counts, per-module activity and lock states                                              | enrolled learner and pinned published version     |
| `/settings`                              | `/v1/me`, `/v1/onboarding`    | loading, session-expired, retry, verified-account facts, learning-profile link, logout, local Light/Dark/System theme mode plus named preset/accent/density/motion presentation preferences | authenticated learner; browser storage optional   |
| `/learn/{programSlug}/complete`          | completion predicate          | incomplete reasons or completed state                                                                                                                               | authoritative required-activity projection        |
| `/certificates/{certificateId}`          | self-scoped certificate API   | issued/not-found/permission states                                                                                                                                  | authoritative completion and immutable issuance   |
| `/offline`                               | static PWA shell              | explains connectivity boundary; no protected data                                                                                                                   | service-worker registration                       |

All mutations use same-origin credentials and server-side Origin checks.
Challenge tokens are JSON-body fields, never query parameters. Onboarding and
draft writes use revision preconditions. User-visible errors do not expose
account existence or internal provider/database details.

The public catalog, program, learner path, module, activity, completion, and
certificate route runtimes read the learner APIs. The old two-module
`course-data.ts` model is retained only as a reference/unit-test fixture; it is
not substituted into the default learner runtime and is not evidence of
deployed course topology.

Learner Google registration is exposed only after explicit learner consent is
recorded in the start request, bound into the signed OAuth transaction, and
revalidated against the exact active consent version before provider exchange.
When the verified Google provider key already belongs to an active person with
no recorded consent, that same transaction records the first consent and
continues with the canonical person; it never creates a duplicate identity.
An older, different consent version remains fail-closed until an append-safe
re-consent contract is approved.
Google authentication remains existing-identity-only; it cannot silently turn
an unknown provider identity into a learner registration. A valid learner
callback that cannot complete redirects to an allowlisted, same-origin
`/auth/callback?result=...` recovery state after the database transaction rolls
back and the OAuth transaction cookie is deleted. Invalid state, host, cookie,
or callback shape continues to fail closed as an RFC 7807 response rather than
being disguised as a recoverable browser state.

Verified password or consent-completing Google registration provisions an
active `learner` membership into the exact configured public learner tenant.
That tenant is distinct from the operations tenant; an operations `owner` or
`admin` role is never reinterpreted as learner authority.

`Start free course` is the explicit action that may establish eligibility for
the exact published global program slug `authority-closers-free-course`. The
server requires an active, verified person, an active learner membership, and
the exact current recorded 18+/Terms/Privacy/operational-email consent. It then
creates or reuses the canonical eligibility fact under
`AC-FREE-SELF-ATTESTATION-v1` and performs enrollment in the same caller-owned
transaction. The fact records the consent version/timestamp and explicit start
action; it is not inferred from analytics, provider state, or session state.
Existing positive facts are reused, while negative, expired, conflicting, or
wrong-course facts fail closed and are not overwritten.

## Identity, onboarding, and free-enrollment API contract

| Method and route                             | Caller                                      | Canonical effect                                                                                                                                                                  |
| -------------------------------------------- | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST /v1/auth/password/register`            | anonymous, safe origin                      | creates active unverified person, credential, consent record, challenge, and outbox intent; returns the same acknowledgement for an existing address                              |
| `POST /v1/auth/password/resend-verification` | anonymous, safe origin                      | supersedes outstanding verification links and enqueues a fresh one only for an eligible unverified password account; response is existence-neutral                                |
| `POST /v1/auth/password/login`               | anonymous, safe origin                      | verifies scrypt credential and verified active person, then issues an opaque host-only session                                                                                    |
| `POST /v1/auth/password/recovery`            | anonymous, safe origin                      | supersedes prior reset links and enqueues one for an eligible active verified account, including a Google-only account setting its first password; response is existence-neutral  |
| `POST /v1/auth/password/verify`              | anonymous, safe origin                      | consumes one verification token, invalidates siblings, verifies the email, and issues a session                                                                                   |
| `POST /v1/auth/password/reset`               | anonymous, safe origin                      | consumes reset token, invalidates siblings, creates or replaces the verifier, and revokes every active session                                                                    |
| `GET /v1/onboarding`                         | authenticated self                          | reads the canonical profile and ETag revision                                                                                                                                     |
| `PUT /v1/onboarding`                         | authenticated self, safe origin, `If-Match` | saves bounded profile fields and explicit status; no inferred recommendation or score                                                                                             |
| `POST /v1/enrollments/free`                  | authenticated learner self, safe origin     | on explicit start, creates/reuses consent-backed eligibility and idempotently creates enrollment/entitlement/provenance in one transaction; client cannot select person or tenant |

Session, OAuth transaction, and email-challenge cryptography require three
mutually independent deployment secrets. Challenge ciphertext exists only to
let the durable post-commit worker create an email; lookup uses a keyed hash.
The versioned verification, reset, and enrollment-welcome renderers and their
external-delivery gate are defined in
[`V0_1_TRANSACTIONAL_EMAIL_CONTRACT.md`](V0_1_TRANSACTIONAL_EMAIL_CONTRACT.md).

## Admin/studio boundary

The separate admin app remains a fail-closed foundation. Catalog publish,
learning correction/review, enrollment grant, job retry, and recovery
reconciliation are server-authorized named commands with tenant, purpose,
idempotency, and audit requirements. Admin UI action wiring and diagnosis
responses are not declared complete in v0.1.

## Responsive and install behavior

- Windows target: current Edge-compatible Chromium web/PWA contract with
  keyboard use, visible focus, minimum 44px mobile touch targets, no horizontal
  overflow at 390px, and install manifest/icons.
- iOS target: Safari/PWA metadata, standalone-capable shell, safe-area-aware
  CSS, and browser storage/network failure states.
- Light, Dark, and System are local browser theme mode preferences only.
  Named presets plus accent, density, and motion are also browser-local
  presentation preferences. They use local storage when available and the
  device color-scheme signal for System; they do not change server profile,
  tenant branding, authority, notification, consent, access, progress, or
  account/session state.
- Engine-level Edge and iOS Safari execution is still required before release;
  responsive viewport checks are not a substitute for those browsers.
