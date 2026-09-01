---
id: SRC-040
type: source
title: Engineering Contract Sources
status: controlled
version: v0.1-alpha
updated: 2026-09-01
controls:
  - "[[API-001-identity-onboarding]]"
  - "[[API-003-learning-evidence]]"
tags:
  - ac/source/controlled
  - ac/source/engineering
---

# Engineering contract sources

| Source                                                                                                                      | Exact controlled ID                            | Applied boundary                                                                        |
| --------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | --------------------------------------------------------------------------------------- |
| [Software Requirements Specification](https://docs.google.com/document/d/1qE_ASXOBN-AAuIglfs4-5Fi_HN3x-jDItBYdb95Ou2g/edit) | `1qE_ASXOBN-AAuIglfs4-5Fi_HN3x-jDItBYdb95Ou2g` | testable behavior, authorization, failure/recovery                                      |
| [Domain, Data, Event & Tenancy Model](https://docs.google.com/document/d/1SUxNYTu30NXwBEbk7os1OBVn4H5qBky-LnzLuOvwaYw/edit) | `1SUxNYTu30NXwBEbk7os1OBVn4H5qBky-LnzLuOvwaYw` | canonical identity, tenant, enrollment, activity, progress, evidence and audit entities |
| [API, Webhook & MCP Contract](https://docs.google.com/document/d/1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0/edit)         | `1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0` | stable `/v1`, idempotency, actor+tenant+resource+action authz, safe errors              |

- controls: [[API-001-identity-onboarding]], [[API-002-catalog-enrollment]], [[API-003-learning-evidence]], [[API-004-session-settings]], [[API-005-admin-operations]].
- implemented by: [[IMP-002-platform-api-domain]] and [[IMP-003-seed-bootstrap]].
- local authorization projection: [G1 route authorization](../../contracts/G1_ROUTE_AUTHORIZATION.md).
