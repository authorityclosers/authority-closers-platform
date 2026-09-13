# Hosted allowance and provider quote authority

This follows frozen `17131950ff0f4873ec8fb43216cbe9b0dd5f429c`. It adds source-owned
API composition and exact stage admission using the existing 0030/0031 schema.
It does not activate an account, contact a provider, launch a VPS worker or deploy.

## Authority and accounting

An admin registry save remains a configuration revision. A separate, approved
deployment artifact must name the exact environment, recipients, finite minute
grants, shared budget and storage bounds. Its stage approvals name an exact source
hash, provider/model/recipe, current registry digest, and coaching profile hash.
They also contain permission, privacy, provider terms, retention, professional,
pricing, external credential and free-allocation references. The deployment pins
the artifact's byte digest; the API/worker reread and revalidate it for admission.
The reference strings alone are not an external attestation verifier.

There is no assumed free tier. Each zero-price approval requires its price-evidence
hash, an explicit verified-free-allocation basis, expiry, maximum request count,
source duration, input bytes, output tokens and an approved no-paid-overage
reference for the bound provider account. Synthetic pricing evidence is
accepted only in the test environment. This boundary supports only approved zero
incremental cost; other prices need a later rate-backed quote implementation and
the existing paid-budget approval/reservation rules. Missing evidence holds work.

POST intake claims only the named immutable grant. It never grants minutes merely
because someone signed in, and a repeated claim cannot add another grant. A new
shared testing budget is explicitly zero; an existing different budget is refused,
not overwritten. Provider reservations remain atomic with the durable job. The
approved call count includes prior reservations conservatively, including failed
attempts. Cache reuse does not create another external effect. Request-count
approvals apply across repeated registrations of the same source for that account.

Source registration also reserves finite byte/count capacity. Awaiting-upload and
deleting records consume it until canonical deletion completes. The global source
byte count deliberately includes all undeleted conversation registrations. These
are source-byte bounds, not a substitute for deployment filesystem quotas covering
derived features/provider responses, native-process memory limits or VPS headroom.

Provider configuration appends serialize with admitted inference using a shared
transaction lock. A quote issued before a configuration change does not authorize
dispatch after the change. Quotes still require the current owner/session, source,
retention, exact immutable input and separately recorded acceptance. Removing or
changing the pinned artifact blocks further admission. Saved reports remain
readable under their normal current owner/recording permission checks.

## HTTP composition

Deployment settings are explicitly opt-in:

- `AC_SALES_XRAY_ENABLED`
- `AC_SALES_XRAY_APPROVAL_PATH` and `AC_SALES_XRAY_APPROVAL_SHA256`
- `AC_SALES_XRAY_STORAGE_ROOT` and `AC_SALES_XRAY_SCRATCH_ROOT`

The roots must be distinct private application-owned roots outside repositories.
The artifact contains no secret values. Its pin and approval evidence must come
from the release-owned reviewed configuration. No live approval artifact or actual
provider allowance is added by this change. The API receives no provider keys.

This is a new composition in the existing AC API. Arbitrarily injecting the local
runtime into staging/production is still rejected. Hosted composition never mounts
the local proof-import endpoint or the localhost demonstration server.
If its approval artifact becomes unavailable at startup, Sales Xray intake stays
disabled while the existing AC API/LMS remains available. The strict standalone
composition function returns an error for release validation; the API records a
content-free capability warning and never substitutes a less restricted runtime.

The configured API adds these owner-only routes with current AC authentication,
exact Origin checks on writes, no tenant selectors and private/no-store responses:

| Route | Effect |
| --- | --- |
| POST `/v1/conversation/recordings/{id}/analysis/quote` | Prepare one exact C2/C4/C5 quote; no consent or provider call |
| POST `/v1/conversation/recordings/{id}/analysis` | Accept the displayed fingerprint/privacy revision and enqueue that stage atomically |
| GET `/v1/conversation/recordings/{id}/analysis` | Read persisted stage/run/checkpoint states; no execution side effects |

Learners select saved checkpoint IDs/stages, never providers, models, profiles,
credential references or budgets. Provider/model/profile choices come from the
approved admin configuration and source-owned approval. The progress response
explicitly says `automatic_progression: false`: this slice supplies the stage API,
not a finished automatic upload-to-report controller or new end-user stage UI.

## Validation and remaining integration

Receipts are saved outside Git under
`D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/`.
The frozen handoff manifest records the final counts and hashes:

| Receipt | Result and scope |
| --- | --- |
| `hosted-authority-final-unit-v2.xml` | 431 unit/composition tests passed |
| `hosted-authority-final-pg.xml` | 6 new PostgreSQL authority tests passed |
| `hosted-authority-pg-regression.xml` | 28 related PostgreSQL regressions passed |
| `hosted-authority-browser-v2.json` | Chromium used real TCP, AC cookie authentication and disposable PostgreSQL for C2/C4/C5 quote, consent, completion and saved-report reads; 18 network events, zero external requests |
| `hosted-authority-final-mypy.txt` | No issues in 13 source modules |
| `hosted-authority-final-ruff.txt` | All changed Python files passed |

The browser proof uses a small test page and a synthetic broker, not the complete
Call Studio upload UI. Its three broker calls are synthetic, not provider network
calls. Reloading/readback reused the saved result. Synthetic provider fixtures
exercise accounting and pipeline behavior; they do not certify real provider
pricing, performance or sales-advice quality. Counts above are separate scopes;
older overlapping reruns are retained and must not be added to them.

Still needed for usable hosted uploads: release-owned approved artifact/allowance
values, private-volume quotas and mounts, a dedicated confined Linux worker and
broker launcher with provider-specific external references, automatic durable
stage progression from a single explicit processing-plan consent, browser/network
proof of that experience, actual cost reconciliation, retention scheduling,
capacity/canary/rollback and coordinated staging/production release. The previous
C0-C6 checkpoint/report and human-review distinctions remain unchanged. Numeric
publication stays held at 95 actual / 100 declared source weights.

The release coordinator selected the existing learner and learner-staging
`/sales-xray` route for first hosted acceptance. It already shares AC routing and
identity; this handoff does not require a new public hostname or a demo container.
Provider-specific worker packaging and volumes are still required. A standalone
client remains in scope, but a proposed hostname is not a verified deployment.
