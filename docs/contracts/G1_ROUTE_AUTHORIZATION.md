# G1 route authorization inventory

This is the code-facing projection of `docs/security/AUTHORIZATION_MATRIX.md`. Controlled identifiers that do not yet exist remain explicitly provisional.

| Route                                             | Actor                                 | Canonical checks                                                                                                         | Matrix      |
| ------------------------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------- |
| `GET /v1/auth/google/start`                       | anonymous or authenticated link actor | safe return path, surface host, pre-redirect durable transaction, server state/nonce/PKCE                                | AUTHZ-01    |
| `GET /v1/auth/google/callback`                    | verified assertion                    | issuer, signature, audience, expiry, verified email, state, nonce, PKCE, one-time locked transaction, deterministic link | AUTHZ-02    |
| `GET /v1/me`                                      | authenticated person                  | self only, active session                                                                                                | AUTHZ-03    |
| `POST /v1/context`                                | authenticated member                  | active membership; server-resolved tenant                                                                                | AUTHZ-04    |
| `GET /v1/programs`                                | anonymous                             | cursor-bounded published global visibility; no draft/protected payload                                                   | AUTHZ-05    |
| `GET /v1/programs/{slug}`                         | anonymous/member                      | published visibility; no draft/protected payload                                                                         | AUTHZ-05    |
| `POST /v1/enrollments/free`                       | eligible learner self                 | self, context, explicit policy inputs, idempotency, approved source                                                      | AUTHZ-06    |
| `GET /v1/learning/{programId}`                    | enrolled learner self                 | entitlement, pinned version, tenant/resource ownership                                                                   | AUTHZ-07    |
| `GET /v1/activities/{activityId}`                 | enrolled learner self                 | prerequisite, entitlement, locked-payload policy                                                                         | AUTHZ-08    |
| `PUT /v1/activities/{activityId}/draft`           | enrolled learner self                 | self, tenant, revision, activity policy                                                                                  | AUTHZ-08    |
| `POST /v1/activities/{activityId}/evidence`       | learner/assigned reviewer             | assignment, evidence policy, append-only result                                                                          | AUTHZ-08/09 |
| `GET /v1/certificates/{certificateId}`            | learner self                          | certificate subject, tenant, completion predicate                                                                        | AUTHZ-10    |
| `POST /v1/admin/program-versions/{id}/publish`    | named admin                           | `catalog_publish`, tenant, immutable transition, audit                                                                   | AUTHZ-12    |
| `GET /v1/admin/learners/{personId}/diagnosis`     | named support/admin                   | `learner_diagnose`, tenant, purpose, redaction, audit                                                                    | AUTHZ-12    |
| `POST /v1/admin/corrections`                      | named admin                           | `learning_correct`, tenant, reason, supersession, audit                                                                  | AUTHZ-12    |
| `POST /v1/admin/enrollment-grants`                | named admin                           | `enrollment_grant`, self-contained reason/provenance                                                                     | AUTHZ-12    |
| `POST /v1/admin/jobs/{id}/retry`                  | named operations                      | `job_retry`, valid state, idempotency, audit                                                                             | AUTHZ-13    |
| `POST /v1/admin/recovery/reconcile`               | named operations                      | `recovery_reconcile`, held state, explicit release set, audit                                                            | AUTHZ-13    |
| `POST /internal/v1/providers/{provider}/webhooks` | verified provider                     | signature, timestamp, inbox dedupe, server-derived ownership                                                             | AUTHZ-14    |

Every row requires a positive case and denial cases for arbitrary subject, wrong tenant, inactive membership/entitlement, guessed identifier, stale revision, duplicate intent, and unsupported role as applicable.
