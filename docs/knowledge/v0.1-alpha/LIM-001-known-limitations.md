---
id: LIM-001
type: limitation
title: Known Limitations and Explicit Non-Claims
status: current
version: v0.1-alpha
updated: 2026-09-04
tags:
  - ac/limitation
---

# Known limitations and explicit non-claims

| ID/boundary             | Current factual state                                                                                                             | Smallest next evidence/action                                                                |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `GAP-RUNTIME-001`       | exact release `65ea3e1` has bounded CI/package/controller smoke; full current browser/device and capability evidence remains open | complete [[GATE-003-exact-release-staging]] evidence                                         |
| `GAP-MEDIA-001`         | approved media/transcript/captions and playback-policy composition are absent                                                     | approve source/policy, compose routes, test watched-interval evidence                        |
| enrollment runtime      | ADR-028 and current code/tests define consent-backed start; exact-current runtime open                                            | fresh consent→membership→start→enrollment replay/isolation proof                             |
| progress/settings/theme | repository has implementation candidates; exact-release route evidence remains open                                               | exact-release canonical-state, accessibility, responsive, first-paint, storage-failure proof |
| Modules 2–4             | titles and prerequisite topology only                                                                                             | do not invent activities or completion behavior                                              |
| evidence mutation       | candidate client/API wiring exists; exact `27fafae` predates it                                                                   | exact-SHA evidence submission, progress, audit and recovery journey                          |
| admin actions           | command APIs exist; UI wiring/privileged staging actions incomplete                                                               | connect only named actions and prove permission/tenant/audit/idempotency                     |
| platform/device         | viewport captures exist; real Edge installed-PWA and iOS Safari/Home Screen open                                                  | run exact-release browser/device matrix                                                      |
| recovery                | restore artifacts exist, but current live restore/RPO/RTO/provider-reconciliation proof remains a gate                            | measured isolated restore with effects held/reconciled                                       |
| production              | explicit `NO-GO`                                                                                                                  | separate production activation evidence and approval                                         |

Explicit non-claims: paid commerce, full B2B/white-label, WhatsApp, native stores, voice simulator, real-call external processing, official autonomous AI scoring, SSO/SCIM, broad integrations, account theme sync, deletion workflow completion, or production launch.

- constrained-by: [[DEC-005-capability-gates]].
- reflected-in: [[WKS-001-agent-handoff-ledger]].
- authoritative status register: [Platform surface status](../../traceability/PLATFORM_SURFACE_STATUS.md).
