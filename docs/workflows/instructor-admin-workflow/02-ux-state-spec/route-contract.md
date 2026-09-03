# Route and screen contract

This is a route inventory for future implementation. It does not add route
handlers or make a candidate path canonical. `registered` means the path is
explicitly named by the controlled IA/Admin contract; `explicit_candidate`
means the source names the surface but leaves the path conditional;
`blocked_not_registered` means the package intentionally supplies no route.

## Hosts and navigation

| Host | Purpose | Package rule |
| --- | --- | --- |
| `app.authorityclosers.com` | learner product | Not redesigned here; only safe cross-surface return awareness |
| `admin.authorityclosers.com` | AC Admin control plane | All listed Admin/Instructor-label routes live here |
| `api.authorityclosers.com` | versioned platform API | UI is a client; server owns authz, tenancy and canonical state |
| ERPNext host | separate ERP trust/user model | No broad ERP screens or learner authority |
| media/files aliases | reserved provider seam | No provider choice or raw-key exposure in this package |

The primary navigation follows the controlled Admin module names conceptually:
Overview, People, Catalog, Learning Operations, Assessments, Practice,
Support, Audit & Compliance and System Health. Commerce, Entitlements, B2B,
Communications, Analytics and Integrations are visible only as source-backed
future module labels or blocked entry points; this package does not add their
workflows.

## Registered and candidate routes

| Screen ID | Route | Status | Entry condition | Exit/return |
| --- | --- | --- | --- | --- |
| `ADM-OVERVIEW` | `/admin` | `registered` | Server grants Admin shell access | Deep-link to an authorized module or return to overview |
| `ADM-USERS` | `/admin/users` | `registered` | Person search/list permission is granted | Open `ADM-USER-DETAIL` or preserve filter on back |
| `ADM-USER-DETAIL` | `/admin/users/{person}` | `registered` | Person id is resolved and actor is authorized | Return to People; optional support/audit reference |
| `INS-PROGRAMS` | `/admin/programs` | `registered` | Catalog read permission is granted | Open content editor or return to overview |
| `INS-CONTENT` | `/admin/programs/{program}/content` | `registered` | Program id and role-scoped catalog permission resolve | Return to catalog; preserve version/deep-link context |
| `INS-PUBLISH` | `/admin/programs/{program}/content` | `registered` | Publish action is rendered only after server authz and validation | Return to content with result/version reference |
| `ADM-PROGRESS` | `/admin/progress` | `explicit_candidate` | Admin route addendum and authz contract exist | Return to person/support context |
| `ADM-AUDIT` | `/admin/audit` | `explicit_candidate` | Restricted audit route and masking/export contract exist | Return to source object with trace reference |
| `ADM-ASSESS-REVIEW` | `BLOCKED_ROUTE:assessment-review` | `blocked_not_registered` | Assessment review route/permissions are unresolved | Stop at blocked capability state |
| `ADM-MEDIA` | `BLOCKED_ROUTE:media` | `blocked_not_registered` | Provider, retention and route contracts are unresolved | Stop at provider gate |
| `ADM-HEALTH` | `BLOCKED_ROUTE:health` | `blocked_not_registered` | Health route surface is not registered | Stop at system-health gate |
| `ADM-SUPPORT-VIEWAS` | `BLOCKED_ROUTE:support-view-as` | `blocked_not_registered` | View-as duration/masking/authz is unresolved | Stop at scoped-support gate |

## Source-backed API references (not implementation)

The following existing `/v1` contract references are useful for future
mapping. They are not new endpoints and do not define missing request fields:

- Catalog: `GET /v1/programs`, `POST|PATCH /v1/programs/{id}`,
  `POST /v1/programs/{id}/publish`, `GET /v1/programs/{id}/modules`,
  `POST /v1/modules`, `PATCH /v1/modules/{id}`,
  `POST /v1/modules/{id}/publish`, `POST /v1/activities`,
  `PATCH /v1/activities/{id}`, `POST /v1/activities/{id}/versions`,
  `POST /v1/activity-versions/{id}/publish`.
- Learning/oversight: `GET /v1/enrollments` and source-backed learning/home
  reads; exact Admin projection is not invented here.
- Assessment: source-backed attempt/review/override endpoints exist in the
  API specification, but this package does not expose a new route or schema.
- Media: `POST /v1/media/uploads`, complete/status/playback/heartbeat and
  caption references are provider-adapter contracts; limits and retention are
  blocked.
- Admin: source-backed overview/users/stuck-learners/jobs/audit/feature flag
  references remain subject to the controlled API/Admin contract.

## Navigation and security rules

- Deep links must re-check authorization and tenant/context on the server.
- Destructive or sensitive actions are non-GET and require confirmation plus a
  reason where the Admin contract requires it.
- Denied states must not reveal whether an unrelated person, tenant or
  resource exists.
- A separate surface does not imply a separate identity system. Do not create
  an Instructor host or account universe (`BLK-02`).
