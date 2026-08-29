# G1 authorization matrix

This is the minimum executable policy inventory. Each row requires allow and deny tests before its endpoint is exposed.

| ID | Actor and context | Resource/action | Allow conditions | Mandatory denial cases |
|---|---|---|---|---|
| AUTHZ-01 | Anonymous | Start authentication transaction | Rate limit; server-generated state/nonce; allowlisted return URL | Client-selected tenant, unsafe return URL, duplicate/replayed transaction |
| AUTHZ-02 | Verified provider assertion | Resolve person and create session | Assertion, issuer, audience, state and nonce valid; deterministic identity link | Ambiguous/conflicting identity, suspended/deleted account, replay |
| AUTHZ-03 | Authenticated person | Read/update self and sessions | Subject is self; policy allows field/action | Arbitrary subject ID, cross-account session mutation |
| AUTHZ-04 | Authenticated member | Select tenant context | Active membership and supported role | Omitted/guessed context where required, inactive or unrelated tenant |
| AUTHZ-05 | Learner in tenant | Read published catalog | Published version, visibility policy, tenant/global scope | Draft payload, hidden protected payload, cross-tenant identifier |
| AUTHZ-06 | Eligible learner self | Create free enrollment | 18+ launch gate, tenant, eligibility and prerequisite valid; idempotency key | Another subject, duplicate side effects, unapproved source |
| AUTHZ-07 | Enrolled learner self | Read learning state | Enrollment and tenant match | Another learner, tenant mismatch, revoked entitlement |
| AUTHZ-08 | Enrolled learner self | Start/progress/complete activity | Active entitlement, pinned version, prerequisites, concurrency and evidence policy | Locked activity, seek-only evidence, stale revision, arbitrary subject |
| AUTHZ-09 | Learner self or explicitly assigned reviewer | Create/submit/review evidence | Activity policy and tenant ownership allow action | Reviewer not assigned, destructive official-result edit |
| AUTHZ-10 | Completion service; learner self for read | Issue/read certificate | Versioned completion predicate true; issuance idempotent and audited | Client-side claim, incomplete course, another learner |
| AUTHZ-11 | Durable notification worker; authorized admin retry | Send launch communication | Outbox intent, approved template/version, dedupe key | Direct public send, duplicate delivery, unapproved recipient |
| AUTHZ-12 | Named support/admin in tenant | Diagnose learner/content/jobs | Fine-grained permission, redaction, purpose and audit | Cross-tenant scope, unrestricted impersonation, hidden write |
| AUTHZ-13 | Named operations actor | Retry/replay job or webhook | Scoped permission, valid state precondition, idempotency and audit | Public/webhook-signature-only admin replay, unsafe terminal state |
| AUTHZ-14 | Verified provider service | Ingest provider webhook | Signature, timestamp, inbox dedupe, server-derived resource/tenant | Client tenant trust, invalid signature, mismatched resource tenant |

## Required tenant-negative suite

`TEN-NEG-001` through `TEN-NEG-012` are defined in the controlled security/data synthesis and must cover cross-tenant reads, writes, relationships, context selection, support view-as, playback, caches/search/retrieval, jobs/webhooks, export/deletion, restored side effects, and analytics.
