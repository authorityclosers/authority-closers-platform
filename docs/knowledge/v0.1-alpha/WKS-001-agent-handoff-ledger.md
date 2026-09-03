---
id: WKS-001
type: workstream
title: Agent-Handoff Ledger
status: observed-worktree-snapshot
version: v0.1-alpha
updated: 2026-09-01
observed_branch: codex/g1-free-course-foundation
observed_head: ccb32c46bfddd742c4d09d9411a8457e80eb053b
tags:
  - ac/workstream
  - ac/handoff
---

# Agent-handoff ledger

Observed on 2026-09-01 before this graph was created: 40 modified tracked files and 39 untracked files outside this knowledge folder. This is a path-based worktree snapshot. It does not identify a live agent, owner, completion state, immutable artifact, deployment, or approved proof.

| Workstream ID                                  | Observed paths                                                                                       | Factual status                                    | Handoff boundary                                                                |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ------------------------------------------------------------------------------- |
| `WS-001` learner experience                    | learner runtime, auth/onboarding forms, shell/states/styles; new progress/settings/theme/draft files | uncommitted implementation candidate              | run local quality gates, review changes, commit exact SHA, then stage           |
| `WS-002` tenancy and consent-backed enrollment | settings/bootstrap/course/onboarding changes; new self-attestation policy; ADR-028                   | uncommitted implementation and decision candidate | prove separate tenant, consent, transaction, replay, isolation on exact release |
| `WS-003` contracts and operational handoff     | route/environment contracts, bootstrap/local runbooks, traceability/status                           | modified repository interpretations               | reconcile with exact code/tests/evidence; controlled Drive remains authority    |
| `WS-004` visual/workflow evidence              | design QA, current candidate captures, staging-audit captures, workflow package                      | untracked documentation/evidence artifacts        | retain evidence scope; do not treat local/reference images as live proof        |
| `WS-005` automated verification                | frontend and Python unit/integration test changes                                                    | uncommitted test evidence                         | run required suites and attach results to the immutable candidate               |
| `WS-006` v0.1 Alpha knowledge graph            | this folder only                                                                                     | documentation work in this task                   | use [[VALIDATION]] and preserve all outside changes untouched                   |

## Handoff rules

- Do not overwrite or absorb the pre-existing dirty worktree.
- Re-read [[SRC-000-control-authority]] and [[SRC-010-implementation-controls]] before changing protected semantics.
- Use [[LIM-001-known-limitations]] to avoid optimistic status promotion.
- Historical exact releases [[EVD-001-staging-27fafae]] and [[EVD-002-auth-81635d1]] remain immutable evidence for their named SHAs; they do not prove `WS-001..005`.
- Next release boundary is [[GATE-003-exact-release-staging]], not production.
