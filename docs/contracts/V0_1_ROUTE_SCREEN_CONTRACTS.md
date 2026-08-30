# v0.1 route and screen contracts

Status: implementation candidate
Deployment status is tracked separately in
[`PLATFORM_SURFACE_STATUS.md`](../traceability/PLATFORM_SURFACE_STATUS.md).

## Learner screen contract

| Browser route | Authority | Primary states and actions | Activation dependency |
|---|---|---|---|
| `/`, `/programs/{slug}` | Public catalog API | loading, empty-without-fixture, retry, published detail, idempotent free enrollment | approved published seed and tenant context |
| `/login` | Identity API | email/password, Google, invalid credentials, verification required, recovery link | deployed identity database and provider evidence |
| `/register` | Identity API | consent-gated registration, password-manager autocomplete, existence-neutral acknowledgement | reviewed environment consent and email delivery |
| `/verify-email` | Identity API | fragment-token consume, success/session, invalid/expired, existence-neutral resend | worker plus approved email adapter |
| `/forgot-password` | Identity API | existence-neutral recovery acknowledgement | worker plus approved email adapter |
| `/reset-password` | Identity API | fragment-token consume, matching new passwords, session revocation, expired/missing link | worker plus approved email adapter |
| `/onboarding` | Person profile | loading, save/resume, revision conflict, skip, complete, retry | authenticated verified person |
| `/home` | `/v1/me`, context, catalog | unauthenticated, empty, retry, server-owned learner context | learner tenant provisioning |
| `/learn/{programSlug}` | canonical learning projection | progress, locked reasons, module path, retry | enrollment pinned to published version |
| `/learn/{programSlug}/module/{moduleId}` | learning projection | ordered activities and prerequisite locks | same as program path |
| `/activity/{activityId}` | activity/draft/evidence APIs | load, offline/error, optimistic draft save, reflection/implementation evidence, lock/permission states | approved activity topology and evidence policy |
| `/learn/{programSlug}/complete` | completion predicate | incomplete reasons or completed state | authoritative required-activity projection |
| `/certificates/{certificateId}` | self-scoped certificate API | issued/not-found/permission states | authoritative completion and immutable issuance |
| `/offline` | static PWA shell | explains connectivity boundary; no protected data | service-worker registration |

All mutations use same-origin credentials and server-side Origin checks.
Challenge tokens are JSON-body fields, never query parameters. Onboarding and
draft writes use revision preconditions. User-visible errors do not expose
account existence or internal provider/database details.

## Identity and onboarding API contract

| Method and route | Caller | Canonical effect |
|---|---|---|
| `POST /v1/auth/password/register` | anonymous, safe origin | creates active unverified person, credential, consent record, challenge, and outbox intent; returns the same acknowledgement for an existing address |
| `POST /v1/auth/password/resend-verification` | anonymous, safe origin | supersedes outstanding verification links and enqueues a fresh one only for an eligible unverified password account; response is existence-neutral |
| `POST /v1/auth/password/login` | anonymous, safe origin | verifies scrypt credential and verified active person, then issues an opaque host-only session |
| `POST /v1/auth/password/recovery` | anonymous, safe origin | supersedes prior reset links and enqueues one only for an eligible password account; response is existence-neutral |
| `POST /v1/auth/password/verify` | anonymous, safe origin | consumes one verification token, invalidates siblings, verifies the email, and issues a session |
| `POST /v1/auth/password/reset` | anonymous, safe origin | consumes reset token, invalidates siblings, replaces the verifier, and revokes every active session |
| `GET /v1/onboarding` | authenticated self | reads the canonical profile and ETag revision |
| `PUT /v1/onboarding` | authenticated self, safe origin, `If-Match` | saves bounded profile fields and explicit status; no inferred recommendation or score |

Session, OAuth transaction, and email-challenge cryptography require three
mutually independent deployment secrets. Challenge ciphertext exists only to
let the durable post-commit worker create an email; lookup uses a keyed hash.

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
- Engine-level Edge and iOS Safari execution is still required before release;
  responsive viewport checks are not a substitute for those browsers.
