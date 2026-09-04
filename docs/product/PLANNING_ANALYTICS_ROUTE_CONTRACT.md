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

The former client analytics write route `POST /v1/analytics/events` is not
registered by the shipped application. Its compatibility adapter is guarded
at composition time and can be enabled only in the test environment; it is
not an activation path.
Canonical domain and audit events are not client-ingestible.

The Phase 2 learner telemetry candidate defines `POST /v1/telemetry/events` as
the bounded batch boundary. It uses the same server-owned proposal taxonomy
but requires an immutable consent grant bound to tenant/person/session, an
explicit policy-scoped retention setting, and a tenant-aware admission seam.
The resolver receives the active caller-owned transaction, re-locks and
re-checks the authoritative grant immediately before insert, and denies the
write if status, purpose, or identity changes. Event IDs are UUID replay keys,
route metadata is an exact server-owned route template, and trace IDs are
server-generated. The default application composition leaves all write
activation seams unset, so this candidate route remains fail-closed and does
not activate an external analytics provider.

Expired analytics are hidden by a non-mutating `retention_expires_at > now`
read predicate. Physical expiry is enforced only by an explicit durable
retention job in a caller-owned transaction, not while serving a read. Account
deletion has an explicit policy-bound purge/anonymization hook: available
batches drain before completion, while locked work leaves the deletion request
processing for a durable continuation. Legal-retention policy classes are not
interpreted by this disposable analytics boundary and fail closed pending a
separate controlled workflow. Before any deployment enables writes, the
admission seam must be backed by a tenant-aware distributed/edge quota or
durable queue policy; the in-process route limiter is only a coarse abuse
shield.

All routes derive tenant and person from the existing authenticated session.
No request body or analytics event can select a tenant. Missing explicit plan
data is `not_configured`; missing retained analytics signal is
`insufficient_signal`; neither state is numeric zero.
