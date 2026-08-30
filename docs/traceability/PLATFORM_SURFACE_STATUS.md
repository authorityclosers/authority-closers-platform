# Authority Closers platform surface status register

Status date: 2026-08-31 (Asia/Kolkata)
Repository branch: `codex/g1-free-course-foundation`
Current observed staging application release: `89be92d510d181574743200476731b7cc333d68c`

This is the canonical code-facing register of platform hostnames and major
routes. It is an implementation/status register, not a replacement for the
controlled Drive requirements set. The source order and document authority are
defined in [`CONTROLLED_SOURCE_REGISTER.md`](CONTROLLED_SOURCE_REGISTER.md).
Only repository documentation, current checked-in code, and current checked-in
route/configuration definitions are used here. No secret, token, or credential
is recorded.

The newer uncommitted v0.1 candidate is summarized in
[`V0_1_ALPHA_HANDOFF.md`](../evidence/V0_1_ALPHA_HANDOFF.md). The live rows below
describe the observed older staging release unless a row explicitly says
candidate. Passing local tests does not change a deployed status.

## Status vocabulary

| Status | Meaning |
|---|---|
| `LIVE_FUNCTIONAL` | Deployed and working for the explicitly stated operational/product scope. It may still be intentionally narrow. |
| `LIVE_PREVIEW` | Reachable in a deployed environment, but static, read-only, fail-closed, incomplete, or otherwise not a product activation. |
| `CONFIGURED_NOT_DEPLOYED` | Defined by current code/configuration or release contracts, but not present in the recorded live application release. |
| `PLANNED` | Named future surface with an identified activation owner/gate, but no current implementation or deployment. |
| `DEFERRED` | Deliberately outside the current slice or rejected by an accepted decision; it must not be exposed by implication. |

## Environment and hostname register

| Hostname / surface | Status | Owner | Environment | Backing implementation | Data source | Auth boundary | Current evidence | Next activation gate |
|---|---|---|---|---|---|---|---|---|
| `authorityclosers.com` | `LIVE_FUNCTIONAL` | Web/operations owner | Public legacy | Existing WordPress site on the pre-platform host; not served by this repository | WordPress host/content | WordPress boundary; outside the platform session-cookie boundary | Foundation status records that the apex still returns HTTP 200 and no WordPress DNS cutover occurred ([implementation status](../../infra/vps-foundation/docs/IMPLEMENTATION_STATUS.md)) | Approve a separately rehearsed WordPress-to-platform cutover, preserve rollback, and verify DNS/edge/origin behavior before changing records |
| `www.authorityclosers.com` | `LIVE_FUNCTIONAL` | Web/operations owner | Public legacy | Existing WordPress site; current behavior is a live page rather than the intended canonical redirect | WordPress host/content | WordPress boundary; outside platform sessions | The legacy apex/`www` remain on the existing host; the current evidence identifies the `www` 200-vs-redirect mismatch | Decide and test the canonical host policy, then install and verify an explicit 301/308 redirect without changing the apex application origin |
| `dipakvishwakarma.com` | `LIVE_FUNCTIONAL` | Infrastructure owner | Public legacy/test | Existing WordPress site and legacy host, retained for testing/rollback | Legacy WordPress host | Separate legacy boundary | Foundation docs explicitly keep the `dipakvishwakarma.com` apex on the old VPS ([foundation README](../../infra/vps-foundation/README.md)) | Retire or migrate only through a separately approved DNS/origin gate |
| `staging.authorityclosers.com` | `LIVE_PREVIEW` | Product/platform | Staging | `apps/learner-web`; Caddy routes this host's `/v1/*` to `ac-staging-api` and other paths to `ac-staging-learner` | Static `freeCourse`/demo view models in `apps/learner-web/app/lib/course-data.ts`; API is separate and currently has no seeded catalog fact | Anonymous preview shell; future browser session is host-only and same-origin | Public staging learner smoke is recorded in [`G1_IMPLEMENTATION_EVIDENCE.md`](../evidence/G1_IMPLEMENTATION_EVIDENCE.md); UI labels itself preview-only and is not connected to account state | Seed one approved versioned course, wire learner reads/mutations, enable Google provider, and pass the G1 critical-journey, auth, accessibility, recovery, and side-effect gates |
| `admin-staging.authorityclosers.com` | `LIVE_PREVIEW` | Platform/operations | Staging | `apps/admin-web`; Caddy routes `/v1/*` to the staging API and other paths to `ac-staging-admin` | No live admin query source; pages render explicit contract/empty states | Cloudflare Access protects ingress; product authorization still requires a named AC session, tenant, role, permission, purpose, and audit | Admin staging access and fail-closed behavior are documented; every current admin page says the API is not connected ([G1 evidence](../evidence/G1_IMPLEMENTATION_EVIDENCE.md)) | Enable product identity, connect server-owned admin context and API actions, protect the hostname with the reviewed Access policy, and pass admin negative-path/audit tests |
| `api-staging.authorityclosers.com` | `LIVE_PREVIEW` | Platform/API | Staging | FastAPI application in `packages/python/ac_platform/http`; Caddy reverse-proxies this host to `ac-staging-api` | PostgreSQL when a route is connected; current public catalog is empty and UI data is not read from this API | Public routes are anonymous; mutations/read-private routes require the API's actor, tenant, entitlement, resource, and Origin checks | The staging API readiness/health path and public staging API smoke are recorded; the implementation evidence calls out that UI action wiring and integrated recovery/security tests remain pending | Deploy the reviewed exact release, seed approved catalog data, configure Google OAuth, connect browser same-origin calls, and pass integrated route/auth/recovery evidence |
| `app.authorityclosers.com` | `CONFIGURED_NOT_DEPLOYED` | Product/platform | Production | Production learner profile in `infra/application/environments/production.env`; Caddy has a production learner/API route | Intended source is production PostgreSQL plus connected providers; no application state is deployed | Host-only product session cookie; same-origin `/v1`; apex WordPress is excluded | Production origins and Caddy handlers are defined, while the infrastructure handoff explicitly says no AC application/database/product source has been deployed ([final handoff](../../infra/vps-foundation/docs/FINAL_HANDOFF.md)) | Promote the exact reviewed staging release after G1/G2 approval, production database/recovery proof, provider approval, and separate production action-time approval |
| `admin.authorityclosers.com` | `CONFIGURED_NOT_DEPLOYED` | Platform/operations | Production | Production admin profile and Caddy admin/API handler | Production PostgreSQL and audited admin state; no production application state currently deployed | Cloudflare Access plus explicit product session/tenant/permission boundary | Production profile is configured in the repository; no production AC application is claimed live ([application README](../../infra/application/README.md)) | Promote the exact release only after Access policy verification, product auth, admin audit/recovery tests, and production approval |
| `api.authorityclosers.com` | `CONFIGURED_NOT_DEPLOYED` | Platform/API | Production | Production FastAPI profile and Caddy API handler | Production PostgreSQL, outbox, providers, and telemetry after activation | API route authorization from [`G1_ROUTE_AUTHORIZATION.md`](../contracts/G1_ROUTE_AUTHORIZATION.md); no public product mutation before gates pass | Production environment and route definitions exist, but the recorded handoff says no application/database has been deployed | Promote the identical, tested image/archive from staging; migrate with backup, keep side effects held, then prove readiness, route authorization, recovery, and rollback |
| `infra.authorityclosers.com` | `LIVE_FUNCTIONAL` | Infrastructure/SRE | Operational | Cloudflare Tunnel to loopback-only foundation Caddy health service | Host/container health state | Operational health is intentionally public, no product session | The tunnel is documented as routing this host to the loopback health service ([implementation status](../../infra/vps-foundation/docs/IMPLEMENTATION_STATUS.md)) | Keep response minimal/no-store; change only through the immutable foundation release and health-path validation |
| `infra.dipakvishwakarma.com` | `LIVE_FUNCTIONAL` | Infrastructure/SRE | Operational | Loopback-only Caddy health endpoint through the named Cloudflare Tunnel | Foundation container/connector health | Public operational health only; no product data or session | `https://infra.dipakvishwakarma.com/healthz` is the documented public health URL and was recorded HTTP 200 with security headers ([implementation status](../../infra/vps-foundation/docs/IMPLEMENTATION_STATUS.md)) | Preserve no-store/security headers and require the foundation public-path health check after every release |
| `ssh.authorityclosers.com` | `LIVE_FUNCTIONAL` | Infrastructure/SRE | Operational | Cloudflare Access SSH application to the VPS SSH daemon; local alias is `ssh ac` | VPS host state | Cloudflare Access policy plus local Ed25519 key; public TCP/22 denied by UFW | The operations runbook records a fresh Access SSH verification and the `ssh ac` ProxyCommand ([operations runbook](../../infra/vps-foundation/runbooks/OPERATIONS.md)) | Re-verify from each operator workstation after Access/key changes; never reopen public SSH as a convenience path |
| `notify.dipakvishwakarma.com` | `LIVE_FUNCTIONAL` | Platform/email | Operational provider DNS | Resend sending-domain verification records | Resend delivery system and Google Workspace receiving system | Provider key remains server-side; DNS verification is public | DKIM/SPF/MX/DMARC verification and a delivered Resend probe are recorded ([implementation status](../../infra/vps-foundation/docs/IMPLEMENTATION_STATUS.md)) | Keep Google Workspace as the receiving authority, preserve legacy SPF senders until old sending is retired, and enable AC transactional email only through a separate provider gate |
| `auth.authorityclosers.com` | `DEFERRED` | Identity/security | Reserved | No host handler or separate auth application | None | Not an active trust boundary; accepted ADR-027 rejects a cross-host browser credential handoff | ADR-027 requires host-only cookies and same-surface callbacks; no `auth` host appears in the environment/Caddy configuration ([ADR-027](../adr/0027-use-host-only-same-origin-browser-sessions.md)) | Do not create DNS or route traffic here unless a new security/API decision explicitly replaces ADR-027 |
| `status.authorityclosers.com` | `PLANNED` | Infrastructure/SRE | Reserved | No repository implementation | Future incident/status data source | Public read-only operational surface; no product session | No host or route is implemented in current Caddy, application, or web apps | Approve status data model, availability/incident ownership, monitoring source, and isolated public deployment |
| `updates.authorityclosers.com` | `PLANNED` | Product/content | Reserved | No repository implementation | Future release/content update source | Public read-only content | No current route or handler | Define ownership, publication workflow, and content/security boundary before DNS |
| `media.authorityclosers.com` | `PLANNED` | Product/platform | Reserved | No repository implementation; current learner renderer explicitly says media is not connected | Future object/media storage and signed delivery | Public media reads only after object authorization; no direct bucket exposure | Current activity UI records “Media not connected”; no media host is configured | Choose media/object contract, access policy, lifecycle, cost guard, and signed-delivery implementation |
| `files.authorityclosers.com` | `PLANNED` | Product/platform | Reserved | No repository implementation | Future user/object file service | Per-tenant/object authorization; never a public bucket alias | No current route or handler | Define file ownership, malware/content checks, retention, R2 policy, and signed URL boundary |
| `help.authorityclosers.com` | `PLANNED` | Product/content | Reserved | No repository implementation | Future support/help content | Public content with protected support actions | No current route or handler | Define help IA, support intake, privacy boundary, and publishing owner |
| `docs.authorityclosers.com` | `PLANNED` | Platform/content | Reserved | Repository engineering docs are not a deployed public docs site | Future public/internal documentation source | Public docs must exclude secrets and internal operational details; internal docs require separate access | Current repository stores docs under `docs/`; no DNS/Caddy/web route exists | Decide public-vs-internal topology and publish through a separately isolated docs build |
| `erp.authorityclosers.com` | `DEFERRED` | Operations/business systems | Reserved | No repository implementation | Future ERP/admin integration | Strongly restricted staff/admin boundary | G1 modular-monolith docs explicitly keep broad ERP/UI capability outside the initial slice ([G1 architecture](../architecture/G1_MODULAR_MONOLITH.md)) | Reopen only with approved ERP scope, tenancy, audit, recovery, and integration contract |
| `mcp.authorityclosers.com` | `DEFERRED` | Platform/agents | Reserved | No repository implementation | Future agent/MCP boundary | Explicit tool identity, tenant/resource/action authorization, and audit required | MCP/agent capability is listed as disabled/deferred in the current architecture and source-gap documents | Reopen only after API/MCP contract, agent authorization, telemetry, abuse, and recovery gates exist |
| `events.authorityclosers.com` | `DEFERRED` | Platform/telemetry | Reserved | No repository implementation | Future event/stream delivery | Signed, replay-safe provider/event boundary; not a browser access shortcut | Events are not a current public host or route; the current architecture keeps broad event infrastructure disabled | Reopen only with an event contract, retention/replay model, tenant isolation, and operational ownership |

## Learner web route register

These routes are implemented by `apps/learner-web` and use the shared shell and
surface-state model. Unless noted otherwise, the current implementation is a
staging `LIVE_PREVIEW`; production has the same route shape only as
`CONFIGURED_NOT_DEPLOYED`. The UI currently renders static/demo data and
explicitly avoids account, enrollment, progress, evidence, email, and
certificate mutations.

### Uncommitted v0.1 candidate delta

The candidate adds connected email/password registration, login, verification
and resend, recovery/reset, optimistic onboarding, API-backed catalog,
enrollment, learner projection, draft/evidence, and certificate adapters plus
an offline-safe PWA shell. These remain `CONFIGURED_NOT_DEPLOYED`; real email,
approved seed data, learner tenant provisioning, PostgreSQL runtime evidence,
and exact-release staging deployment are still required. See the route/screen
contract and handoff for the precise boundary.

| Route | Status on staging | Owner | Backing implementation | Data source | Auth boundary | Current evidence | Next activation gate |
|---|---|---|---|---|---|---|---|
| `/` | `LIVE_PREVIEW` | Product/web | `apps/learner-web/app/page.tsx` | Static `freeCourse` view model | Anonymous | Preview notice and static course CTA | Replace static catalog read with `/v1/programs` and preserve honest empty/error states |
| `/privacy` | `CONFIGURED_NOT_DEPLOYED` | Legal/product | `app/privacy/page.tsx` and `components/policy-page.tsx` in the current working tree | Staging-scoped static policy copy | Public | Present in current code, absent from recorded deployed release; explicitly not final production terms | Review legal copy and deploy the reviewed release; create production legal content separately |
| `/terms` | `CONFIGURED_NOT_DEPLOYED` | Legal/product | `app/terms/page.tsx` and `components/policy-page.tsx` in the current working tree | Staging-scoped static policy copy | Public | Present in current code, absent from recorded deployed release; explicitly not final production terms | Same as `/privacy`: legal approval plus reviewed staging deployment, then production-specific terms |
| `/programs/{slug}` | `LIVE_PREVIEW` | Product/catalog | `app/programs/[slug]/page.tsx` | Static `getProgramBySlug`; canonical API counterpart is `GET /v1/programs/{slug}` | Anonymous/member published visibility in the API; current UI does not authenticate | `course-data.ts` supplies `free-course`; UI labels the version seam as not connected | Seed/publish one immutable program version and bind the page to the API response/ETag |
| `/login` | `LIVE_PREVIEW` | Identity/web | `app/login/page.tsx`, `components/login-form.tsx` | No account data; generated same-origin auth link | Anonymous | Login UI says authentication is not connected; staging API currently fails closed when no Google provider is configured | Configure and test Google web client, Infisical pair, callback allowlist, transaction replay/CSRF/PKCE, and session issuance |
| `/auth/callback` | `LIVE_PREVIEW` | Identity/web | `app/auth/callback/page.tsx` | No callback payload is trusted by the page | Anonymous shell; API callback owns assertion verification | Page is a callback-state display shell; it does not replace the server callback | Wire success/error result from the server callback and verify return-path/surface binding |
| `/onboarding` | `LIVE_PREVIEW` | Identity/product | `app/onboarding/page.tsx`, `components/onboarding-form.tsx` | Static form state; no profile write | Anonymous preview | Form is disabled and says profile creation is not connected | Define profile fields/consent and connect an authenticated, idempotent server command |
| `/home` | `LIVE_PREVIEW` | Learning/product | `app/home/page.tsx` | Static `demoLearner` and `freeCourse` | Intended learner session; current UI has no live session | Static progress `0 / 5` and preview-only notices | Resolve `/v1/me`, context, enrollment, and authoritative progress; verify another-device resume |
| `/learn/{programSlug}` | `LIVE_PREVIEW` | Learning/product | `app/learn/[programSlug]/page.tsx` | Static program/module view models | Intended enrolled learner; current route is preview | Preview path and “version seam not connected” are explicit | Bind to `GET /v1/learning/{programId}` and reconcile slug-to-UUID route contract |
| `/learn/{programSlug}/module/{moduleId}` | `LIVE_PREVIEW` | Learning/product | `app/learn/[programSlug]/module/[moduleId]/page.tsx` | Static module/activity view models | Intended enrolled learner with prerequisite checks | Preview-only module path with no live evidence writes | Bind module payload to pinned server version and enforce prerequisite/locked payload behavior |
| `/activity/{activityId}` | `LIVE_PREVIEW` | Learning/product | `app/activity/[activityId]/page.tsx` and activity renderers | Static activity definitions; media not connected | Intended enrolled learner/reviewer for evidence; current actions disabled | Renderer preview, “Media not connected,” and disabled navigation are explicit | Connect activity read, draft/evidence commands, media policy, and video evidence endpoints after policy resolver activation |
| `/learn/{programSlug}/complete` | `LIVE_PREVIEW` | Learning/certificates | `app/learn/[programSlug]/complete/page.tsx` | Static checklist | Intended enrolled learner; no completion mutation | Completion is explicitly preview-only | Connect authoritative completion evaluation and immutable certificate issuance |
| `/certificates/{certificateId}` | `LIVE_PREVIEW` | Certificates/product | `app/certificates/[certificateId]/page.tsx` | Static `demoCertificate`; API counterpart is self-scoped certificate read | Intended certificate subject only; current view is demo | “Not issued · preview only” is explicit | Issue only from authoritative completion predicate, then read via `GET /v1/certificates/{certificateId}` |

## Admin web route register

These routes are contract previews. They are reachable only on the admin
surface, but current pages do not perform API calls or privileged writes.

| Route | Status on staging | Owner | Backing implementation | Data source | Auth boundary | Current evidence | Next activation gate |
|---|---|---|---|---|---|---|---|
| `/` | `LIVE_PREVIEW` | Platform/operations | `apps/admin-web/app/page.tsx` | Static surface cards; no admin data | Cloudflare Access plus future AC product admin session | Page says it awaits the authorized API and records no action | Connect server-owned context and route each card only to authorized API handlers |
| `/people` | `LIVE_PREVIEW` | Support/admin | `app/people/page.tsx` | No learner lookup; empty state | `learner_diagnose`, tenant, purpose, redaction, audit | Page explicitly says no diagnosis request ran | Implement/install diagnosis route, then prove authorization, redaction, audit, and no view-as escalation |
| `/people/corrections` | `LIVE_PREVIEW` | Support/admin | `app/people/corrections/page.tsx` and admin forms | No correction command | Named `learning_correct` permission, tenant, reason, supersession, audit | Preview form never mutates evidence | Connect `POST /v1/admin/corrections` and verify append-only correction chain |
| `/people/grants` | `LIVE_PREVIEW` | Support/admin | `app/people/grants/page.tsx` and admin forms | No entitlement state | Named `enrollment_grant` permission, tenant, published version, reason, audit | Preview form never creates access | Connect `POST /v1/admin/enrollment-grants` and prove provenance/idempotency |
| `/catalog` | `LIVE_PREVIEW` | Catalog/admin | `app/catalog/page.tsx` | No catalog query; no version selected | Named `catalog_publish` permission, tenant, immutable transition, audit | Page explicitly says catalog API is not connected | Connect catalog lookup and `POST /v1/admin/program-versions/{id}/publish`; reconcile content/module count first |
| `/learning-operations` | `LIVE_PREVIEW` | Operations/admin | `app/learning-operations/page.tsx` | No queue/recovery state | Named `job_retry`/`recovery_reconcile` permissions, held-state and audit boundary | Page says no queue or live job state is connected | Connect operations API, restore-hold state, reconciliation set, and audit evidence |

## API route register

The API is implemented in `packages/python/ac_platform/http`. The checked-in
composition root installs the identity, course, learning, certificate, admin,
and operations routers. API status below is the staging status; the same route
families are production configuration only until the production application is
promoted.

| Route family / exact routes | Status on staging | Owner | Backing implementation | Data source | Auth boundary | Current evidence | Next activation gate |
|---|---|---|---|---|---|---|---|
| `GET /health/live`, `GET /health/ready` | `LIVE_FUNCTIONAL` | Platform/SRE | `packages/python/ac_platform/http/app.py` | Process identity; readiness performs authenticated PostgreSQL `SELECT 1` | No product auth; operational response only | Health routes are part of the API composition and are used by the application health checks | Keep no-store/minimal output and include release identity in deployment smoke evidence |
| `GET /v1/auth/google/start` | `LIVE_PREVIEW` | Identity/security | `http/auth.py` plus OAuth transaction codec/provider port | PostgreSQL transaction record; Google provider when configured | Anonymous/authenticated link actor, safe return path, surface-host check, state/nonce/PKCE | Route exists, but the recorded staging behavior is fail-closed with `identity_provider_unavailable` when provider config is absent | Configure the Google client and both staging callbacks, then run positive, denial, replay, expiry, and wrong-surface tests |
| `GET /v1/auth/google/callback` | `LIVE_PREVIEW` | Identity/security | `http/auth.py`, `auth_transactions.py`, `identity_provider.py` | Google assertion plus locked one-time PostgreSQL transaction | Verified assertion, issuer/signature/audience/expiry/email, state/nonce/PKCE, host-only callback cookie | Server-side callback route and security tests exist; no live provider transaction is claimed | Enable provider, prove session issuance/linking/revocation, and verify exact learner/admin same-surface redirects |
| `GET /v1/me`, `GET /v1/context`, `POST /v1/context`, `POST /v1/sessions/{session_id}/revoke`, `POST /v1/auth/logout` | `LIVE_PREVIEW` | Identity/security | `http/auth.py` | Canonical identity, memberships, sessions in PostgreSQL | Opaque host-only session cookie; active person/membership/tenant; safe Origin for mutations | Route implementations and negative tests exist; no authenticated staging cohort is claimed | Configure Google/session secrets, wire browser calls, and pass session lifecycle, tenancy, CSRF, revocation, and deletion/recovery tests |
| `GET /v1/programs`, `GET /v1/programs/{slug}` | `LIVE_PREVIEW` | Catalog/product | `http/course.py` | Published global `Program`/`ProgramVersion`/`Module`/`Activity` rows in PostgreSQL | Anonymous published visibility; member access cannot reveal drafts/protected payloads | Current audit identified the deployed API collection as empty while the learner preview is populated from static code | Seed and publish one source-approved immutable program; make learner page/API use one response contract and verify empty/non-empty cases |
| `POST /v1/enrollments/free` | `LIVE_PREVIEW` | Enrollment/product | `http/course.py` plus enrollment application | PostgreSQL enrollment, entitlement, provenance, idempotency, audit, outbox | Authenticated eligible learner self; active tenant; explicit `Idempotency-Key`; safe Origin | Route and domain tests exist, but no live UI mutation is connected | Connect onboarding/enrollment UI, seed a published version, enable email only through the provider gate, and prove duplicate/replay behavior |
| `GET /v1/learning/{programId}`, `GET /v1/activities/{activityId}` | `LIVE_PREVIEW` | Learning/product | `http/learning.py` | PostgreSQL pinned enrollment/version, activities, progress, drafts/evidence | Enrolled learner self, entitlement, prerequisite, tenant/resource ownership | Route code and domain tests exist; UI currently uses slug/static data and does not call them | Reconcile UUID API identifiers with web slug/module paths, then connect authoritative reads and locked states |
| `PUT /v1/activities/{activityId}/draft` | `LIVE_PREVIEW` | Learning/product | `http/learning.py` | PostgreSQL durable draft with revision/idempotency | Enrolled learner self, tenant, optimistic `If-Match`, safe Origin | Implemented/tested server contract; browser action remains preview-disabled | Connect form/save/resume UI and run reconnect, expiry, conflict, another-device, and body-limit tests |
| `POST /v1/activities/{activityId}/evidence`, `POST /v1/evidence/{submissionId}/review` | `LIVE_PREVIEW` | Learning/review | `http/learning.py` | Append-only evidence/submission/review records, audit, progress | Learner/assigned reviewer, tenant/resource ownership, evidence policy, append-only result | Server route/domain tests exist; current UI says evidence/review is not connected | Connect activity forms and reviewer workflow, then pass abuse, assignment, correction, audit, and telemetry tests |
| `POST /v1/activities/{activityId}/playback/start`, `/heartbeat`, `/finish` | `CONFIGURED_NOT_DEPLOYED` | Learning/media | Conditional route definitions in `http/learning.py` behind a `policy_resolver` | PostgreSQL playback/evidence policy and unique watched intervals | Enrolled learner, activity policy, server-issued playback/evidence contract | Code declares these routes only when a policy resolver is supplied; current composition does not supply one and media is not connected | Implement/review policy resolver, media authorization, interval anti-seek rules, rate/body limits, then explicitly install and test routes |
| `GET /v1/certificates/{certificateId}` | `LIVE_PREVIEW` | Certificates | `http/certificates.py` | Immutable certificate and completion predicate in PostgreSQL | Certificate subject self, tenant, completion predicate | Route code/tests exist; UI uses static preview certificate and says not issued | Connect authoritative issuance/read and verify duplicate issuance, revocation policy, privacy, and tenant-negative cases |
| `POST /v1/admin/program-versions/{id}/publish`, `POST /v1/admin/corrections`, `POST /v1/admin/enrollment-grants` | `LIVE_PREVIEW` | Admin/catalog/enrollment | `http/admin_learning.py` | PostgreSQL version, correction, entitlement, audit, idempotency, outbox state | Named permission, active tenant, purpose/reason, immutable/append-only policy, audit | Router is composed and admin UI is reachable, but UI performs no request and no privileged staging action is claimed | Connect admin server actions and pass actor/tenant/resource negative cases, audit-chain, idempotency, and recovery-hold tests |
| `GET /v1/admin/learners/{personId}/diagnosis` | `PLANNED` | Support/admin | Contract row in [`G1_ROUTE_AUTHORIZATION.md`](../contracts/G1_ROUTE_AUTHORIZATION.md); `admin_learning.py` comment says diagnosis is not installed | Future redacted learner aggregate from canonical PostgreSQL | Named support/admin, tenant, purpose, redaction, audit; no arbitrary subject or impersonation | The route is specified by contract but is not installed by the current composition; admin UI explicitly reports no lookup | Install a reviewed resolver/route, define response redaction and source entities, then pass view-as/tenant/permission/audit tests |
| `POST /v1/admin/jobs/{id}/retry`, `POST /v1/admin/recovery/reconcile` | `LIVE_PREVIEW` | Operations/recovery | `http/operations.py` | PostgreSQL durable jobs/outbox/recovery holds and audit | Named operations permission, valid state, idempotency, explicit reconciliation set, audit | Router is composed; admin operations page says no live queue/recovery state is connected | Connect server-owned queue state, prove restored jobs remain held, and run retry/reconcile crash/replay tests |
| `POST /internal/v1/providers/{provider}/webhooks` | `DEFERRED` | Providers/operations | Conditional webhook router in `http/operations.py` | Provider inbox plus canonical transaction/outbox state | Verified provider signature/timestamp, inbox dedupe, server-derived ownership; never direct access grant | Router is conditional on webhook adapters and no current provider callback activation is claimed | Reopen only after an approved provider adapter, webhook secret, replay/ordering contract, and side-effect reconciliation gate |
| `/docs`, `/openapi.json` | `LIVE_PREVIEW` (deployment drift) | Platform/API | FastAPI composition sets `docs_url` and `openapi_url` to `None` for staging/production | Generated API schema only | Must not be public on staging/production | The checked-in code disables both paths, while the recorded deployed staging release was observed exposing them; this is a release drift, not an intended surface | Deploy the exact reviewed code and assert 404/no schema on staging/production; retain docs only in local/test environments or an explicitly protected internal surface |
| `/redoc` | `DEFERRED` | Platform/API | `redoc_url=None` in FastAPI composition | None in staging/production | None | No ReDoc route is declared | Keep disabled unless a protected documentation decision is approved |

## Drift reconciliation and release gates

### 1. Empty API versus static preview

The learner shell and API currently have different sources of truth:

```text
current learner preview: apps/learner-web/app/lib/course-data.ts
                         └─ free-course, 2 modules, 5 activities

current API contract:    GET /v1/programs and GET /v1/programs/{slug}
                         └─ PostgreSQL published catalog; current collection empty
```

This is classified as `LIVE_PREVIEW`, not as a working product. The next
activation gate is one approved, versioned PostgreSQL course seed and one
learner API adapter. Static demo data must then be removed from the live data
path or retained only as an explicitly labeled test fixture.

### 2. Two modules versus the controlled four-module direction

The current static implementation declares two modules and five activities in
`course-data.ts`. The controlled first-slice direction records a four-module
course shape, while the local requirement matrix fixes the five activity kinds
and the permanent `Program -> Module -> Activity` hierarchy. The repository
therefore cannot silently choose either count. This is an unresolved content /
controlled-source reconciliation, and the catalog publish gate must remain
closed until the authoritative course topology is explicitly approved and
seeded.

### 3. `www` redirect

The legacy `www` surface is live and currently behaves as a page/200 response,
not as a verified canonical redirect. This does not authorize changing the
WordPress DNS or apex. The redirect policy must be decided and tested as a
separate legacy-web gate before it is recorded as functional.

### 4. Separate auth hostname versus same-origin callbacks

`auth.authorityclosers.com` is reserved/deferred. ADR-027 explicitly chooses
host-only learner/admin cookies and same-surface server callbacks:

```text
staging learner: https://staging.authorityclosers.com/v1/auth/google/callback
staging admin:   https://admin-staging.authorityclosers.com/v1/auth/google/callback
production learner: https://app.authorityclosers.com/v1/auth/google/callback
production admin:   https://admin.authorityclosers.com/v1/auth/google/callback
```

The API hostname remains available for health/integration/non-browser clients;
it is not a browser credential handoff host.

### 5. API documentation exposure

The code and the recorded deployed release disagree. The intended rule is
that staging/production expose neither `/docs` nor `/openapi.json`; the current
FastAPI composition implements that rule. The old deployed staging release is
therefore a `LIVE_PREVIEW` security/configuration drift that must be corrected
by exact-release deployment and a negative smoke test, not by documenting the
exposure as a supported URL.

### 6. Route shape reconciliation

The web route is slug-shaped (`/learn/{programSlug}` and
`/learn/{programSlug}/module/{moduleId}`), while the API learning read is
UUID-shaped (`/v1/learning/{programId}`). The API is canonical for identity,
authorization, pinned version, and progression; the web slug is navigation.
The activation gate is an explicit server/API view-model adapter that resolves
slug to the canonical program/version and never lets a URL identifier grant
access. Playback is a separate conditional route family and is not active until
its policy resolver and media boundary are installed.

### 7. What “live” means here

The public WordPress site and foundation operational endpoints are live for
their stated legacy/health/SSH purposes. The AC learner/admin/API application
is currently a staging preview plus production configuration. No row in this
register authorizes a production application cutover, product mutation, public
media/file service, broad ERP, MCP, or event platform.

## Canonical activation order

1. Reconcile controlled content topology and route/component/API source gaps.
2. Correct the exact-release staging drift: docs exposure, deployed release
   identity, and any stale Caddy/application wiring.
3. Seed one approved catalog version and connect learner/API reads.
4. Configure/test Google OAuth and host-only sessions; connect admin context.
5. Connect enrollment, learning, evidence, completion, certificate, and the
   fake email outbox in staging while external side effects remain held.
6. Complete independent security, accessibility, abuse, telemetry, backup,
   offsite restore, RPO/RTO, and side-effect reconciliation evidence.
7. Promote the identical artifact to production only after a separate approval;
   keep `authorityclosers.com`/`www` WordPress DNS unchanged until its own
   migration gate passes.
