---
id: IMP-005
type: implementation
title: Workflow and Design Handoff Artifacts
status: uncommitted-documentation
version: v0.1-alpha
updated: 2026-09-01
tags:
  - ac/implementation/workflow
---

# Workflow and design handoff artifacts

The current worktree contains a separate workflow package with six journeys, 33 stable screens, 81 state transitions, design context, decision log, QA checklist, and structural validation:

- [Start here](../../workflows/v0.1-alpha-experience/README.md)
- [Journeys](../../workflows/v0.1-alpha-experience/01-research-journeys/journeys.md)
- [Behavioral specification](../../workflows/v0.1-alpha-experience/02-ux-state-spec/behavioral-spec.md)
- [State transition matrix](../../workflows/v0.1-alpha-experience/02-ux-state-spec/state-transition-matrix.csv)
- [AI design context](../../workflows/v0.1-alpha-experience/04-ai-context/ai-design-context.json)
- [PlantUML source](../../workflows/v0.1-alpha-experience/04-ai-context/v0.1-alpha-experience.puml)
- [QA/release checklist](../../workflows/v0.1-alpha-experience/05-handoff-qa/qa-release-checklist.md)
- [Validation report](../../workflows/v0.1-alpha-experience/05-handoff-qa/validation-report.md)

This graph reuses those stable IDs and evidence boundaries. It does not promote the package from reference-ready to staging-ready or production-approved.

- derives-from: [[SRC-070-repository-interpretations]].
- evidenced-by: [[EVD-004-workflow-structural-validation]].
- hands-off-to: [[GATE-003-exact-release-staging]].
