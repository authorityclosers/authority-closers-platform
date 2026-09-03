# Planning and analytics route contract

Status: proposal pending controlled-source promotion.

| Learner surface | API | Authority |
| --- | --- | --- |
| `/home` | `GET /v1/learning/home` | Mixed response with separate explicit-plan, canonical-progress, and descriptive-analytics source fields |
| `/progress` | `GET /v1/learning/progress` | Existing canonical activity progress only |
| `/calendar` | `GET /v1/learning/calendar` | Explicit plan items grouped under `today`, `week`, and `month` |

Supporting reads are `GET /v1/learning/plans`,
`GET /v1/learning/up-next`, and `GET /v1/learning/insights`.
`GET /v1/analytics/taxonomy` exposes only proposal event definitions.

The client analytics write route is `POST /v1/analytics/events`. It accepts
only the five `analytics.*` events in the taxonomy, with bounded scalar
payloads and product-analytics consent. It is fail-closed until application
composition supplies both a verified consent resolver and an explicit
retention policy. Canonical domain and audit events are not client-ingestible.

All routes derive tenant and person from the existing authenticated session.
No request body or analytics event can select a tenant. Missing explicit plan
data is `not_configured`; missing retained analytics signal is
`insufficient_signal`; neither state is numeric zero.
