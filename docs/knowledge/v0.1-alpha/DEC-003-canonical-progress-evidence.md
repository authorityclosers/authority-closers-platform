---
id: DEC-003
type: decision
title: Canonical Progress and Evidence Authority
status: accepted
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/decision/progress
  - ac/decision/evidence
---

# Canonical progress and evidence authority

Progress, completion, and evidence are canonical server-owned product state. Analytics events and UI state are secondary and never grant access, progress, payment, score, or completion. Evidence mutation is append-safe; audit-critical corrections supersede rather than erase history.

Video completion is participation evidence from versioned server-authoritative unique intervals, not mastery. Implementation challenges record supported learner evidence without asserting real-world certainty. Review/Improve do not invent coach or AI scoring.

- controlled-by: [[SRC-000-control-authority]], [[SRC-040-engineering-contracts]], [[SRC-050-trust-operations]].
- controls: [[API-003-learning-evidence]], [[ACT-01-watch]], [[ACT-02-reflection]], [[SF-EVIDENCE-001-implement-review-improve]], [[PROG-01-progress]].
- validated-by: [[GATE-002-G1-free-course]] and [[IMP-004-tests]].
