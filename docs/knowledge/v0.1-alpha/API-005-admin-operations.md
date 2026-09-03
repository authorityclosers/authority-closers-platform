---
id: API-005
type: api-contract
title: Admin and Recovery Command API Contract
status: foundation-only
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/api/admin
---

# Admin and recovery command API contract

Named commands include catalog publish, learning correction, enrollment grant, held-job retry, and recovery reconciliation. Each command requires current server authorization, explicit tenant/context, named permission, purpose/reason, safe confirmation where applicable, idempotency, and append-safe audit.

Representative paths:

- `POST /v1/admin/program-versions/{id}/publish`
- `POST /v1/admin/corrections`
- `POST /v1/admin/enrollment-grants`
- `POST /v1/admin/jobs/{jobId}/retry`
- `POST /v1/admin/recovery/reconcile`

Routine direct database edits are not an operational recovery path. Restored jobs/outbox remain held until explicit reconciliation.

- controlled-by: [[SRC-050-trust-operations]].
- called-by: [[JRN-06-admin-operations]].
- implements: [admin learning HTTP](../../../packages/python/ac_platform/http/admin_learning.py) and [operations HTTP](../../../packages/python/ac_platform/http/operations.py).
- validated-by: [[GATE-002-G1-free-course]], [[GATE-003-exact-release-staging]], and [[IMP-004-tests]].
