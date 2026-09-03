# Scope and authority

## Objective

Define a small, implementation-ready workflow/UI architecture package for
future instructor-oriented authoring/review and AC product-admin operations.
The package exercises the permanent Program → Module → Activity, evidence,
progress, content-version, audit and provider-adapter boundaries without
building the future products.

## Surface boundary

| Surface | Controlled boundary | In scope here | Explicitly out of scope |
| --- | --- | --- | --- |
| Learner product | `app.authorityclosers.com` | Safe return/deep-link awareness only | Learner screens, learner navigation or learner behavior redesign |
| AC Admin | `admin.authorityclosers.com` | Narrow read/diagnose/control-plane workflows | Broad ERP screens, speculative dashboards, direct DB operations |
| Instructor Studio | No separate controlled host or role | Proposed label for existing Content Manager / Coach-Reviewer capabilities | New identity, new host, new authorization role or unapproved permission union |
| API | `api.authorityclosers.com`, versioned `/v1` | Existing source-backed route references | New endpoints, schemas, provider behavior or client authority |
| Media | Reserved `media.authorityclosers.com` alias | Lifecycle and gate states | Selecting a provider, codec/size/SLA, real-call processing |

The Admin specification explicitly separates `admin.authorityclosers.com`
from the learner shell and keeps ERPNext on a different trust/user model. This
package follows that split. It does not turn future B2B readiness into a full
organization, manager, seat or white-label product.

## Authority order

1. Current user decisions and hard law/platform/security/privacy constraints.
2. Controlled Drive sources fetched by exact ID from the source manifest.
3. Repository contracts and recorded assurance gates.
4. This package's behavior matrix and design inference.
5. Text-only layout references and any future generated visual.

Code or a polished visual cannot become a source of truth for a missing
business rule. Any contradiction is logged and escalated.

## Canonical roles used by this package

These names come from the controlled Admin role model. They are not expanded
with new permissions here.

| Canonical role | Product surface | Controlled authority boundary |
| --- | --- | --- |
| Platform Owner | AC Admin | Full platform governance; no routine break-glass use |
| Technical Administrator | AC Admin | Infrastructure, integrations, flags and diagnostics; cannot alter business scores without explicit grant |
| Business Administrator | AC Admin | Catalog, offers, enrollments, support and reports; cannot manage secrets/infrastructure |
| Finance Operator | AC Admin / finance operations | Orders, payments, refunds and invoice reconciliation; no content or score editing |
| Content Manager | Instructor Studio / Catalog | Programs, modules, activities and publication; cannot grant paid access without entitlement permission |
| Coach / Reviewer | Instructor Studio / Assessment Review | Review submissions, reasoned score overrides and interventions; no payment/refund authority |
| Support Agent | AC Admin / Support | Cases, access diagnosis and limited resend/retry; masked payment data and no rubric/config edits |
| Auditor / Read-only | AC Admin / Audit | Reports, audit history and exports; no mutations |
| Organization Owner / Manager | Future B2B only | Tenant-scoped organization/team/reporting capability; deferred from this package |
| Service Account | API/jobs | Narrow machine action; no interactive login |

### Instructor label decision

`Instructor Studio` is a navigation/product label only. The controlled role
register does not define an `Instructor` authorization role or a permission
union between Content Manager and Coach / Reviewer. Until that decision is
explicitly approved, any screen that needs both capabilities must evaluate the
existing role assignment(s) server-side and show only the granted action.

## Blocked behavior register

The following behaviors are intentionally marked **BLOCKED** rather than
inferred:

| ID | Blocked behavior | Why it is blocked | Smallest next authority |
| --- | --- | --- | --- |
| BLK-01 | Exact `Instructor` role, permission union and approval ownership | No canonical Instructor role exists; Admin names Content Manager and Coach / Reviewer separately | Approved role/permission decision propagated to Admin, API, Security and QA |
| BLK-02 | New instructor hostname or account universe | IA defines Admin host and does not register an Instructor host | IA/ADR decision only if a separate product is actually needed |
| BLK-03 | Full B2B organization/manager/seat/white-label UI | BRD/AC-IMP explicitly defer scaled B2B; architecture readiness is not product scope | Real contract + tenant-isolation/privacy gate |
| BLK-04 | Paid checkout, billing, refunds, learner counts or revenue values in UI | Payment/entitlement and management values are protected business semantics; no values are provided here | Controlled product/finance decision and release evidence |
| BLK-05 | Autonomous official AI scoring or new score classes | AC-SVAL requires human-confirmed official results until gates pass; exact score classes remain guarded | AC-SVAL release gate and controlled score contract |
| BLK-06 | Real-call recording, transcription or external-AI processing | P0 call-data gate requires notice/consent, retention, provenance, provider and professional review | AC-GOV-AUD/AC-UXA/AC-SVAL activation record |
| BLK-07 | Assessment question schema, attempt limits and publish approval policy | SRS/PRD establish capability and versioning but do not fully define the authoring schema or approval separation | Assessment contract + rubric/QA decision |
| BLK-08 | Media provider, codec/size/SLA, upload resumability guarantee or retention values | Sources require an adapter and lifecycle, not vendor-specific behavior | Provider/Privacy/SRE review and test evidence |
| BLK-09 | Admin subroutes for Media, Assessment Review, Health and View-as | IA names modules, but only some admin route paths are registered | IA route addendum with authz matrix |
| BLK-10 | Moderation, community, messaging, reminders and publication audience rules | Deferred or not defined for this product surface | Explicit product scope and policy decision |
| BLK-11 | Exact bulk partial-success semantics | Admin requires preview/audit, but detailed bulk outcome contract is not frozen | API/UXS/QA contract |
| BLK-12 | Admin MFA/step-up timing, view-as duration and masking catalogue | Security treats hardening and exact masking/duration as staged/unfinished | Security/Admin hardening decision |
| BLK-VIS-01 | Semantic-to-brand color and font mapping | UI System provides semantic tokens but no final Admin brand palette/typeface | Approved UI System token addendum |
| BLK-VIS-02 | Non-sensitive visual fixtures | No source-authorized Admin fixture set was supplied | Content/privacy-approved fixture pack |
| BLK-VIS-03 | Device/accessibility visual evidence | Text wireframes do not prove reflow, contrast, focus or target-size behavior | Implemented responsive prototype plus AC-UXA evidence |

## Non-negotiable guardrails

- Do not use the learner app as the Admin or Instructor surface.
- Do not make analytics a source of truth for access, progress, scores or
  publication.
- Do not overwrite audit-critical history; corrections supersede.
- Do not use direct database edits as operational recovery.
- Do not claim a role, permission, provider, score, payment, learner count or
  publication policy not found in the controlled sources.
- A P0 blocks the affected capability, not unrelated foundation work.
