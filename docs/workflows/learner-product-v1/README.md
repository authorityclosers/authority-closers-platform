# Authority Closers learner product v1 workflow

Status: **visual exploration and contract reconciliation in progress**
Workstream ID: `AC-WF-LEARNER-V1`
Baseline date: 2026-09-02

## Visual review center

Open [`00-start-here/ui-review-center.html`](00-start-here/ui-review-center.html)
to review all six generated desktop/mobile directions, the selected learner
flow, implementation evidence, and the production UI source files in one place.

This package expands the narrow v0.1 free-course foundation into a coherent
learner product. It does not declare any generated screen approved or live.
Controlled business, security, tenancy, progress, and audit semantics remain
authoritative. Founder direction may supersede presentation and product-surface
decisions only after the change is recorded here and reconciled into the
controlled documents.

## Required sequence

1. Read `00-start-here/product-brief.md`.
2. Use `01-research-journeys/surface-inventory.md` as the page/tab/section list.
3. Use `01-research-journeys/workflows.md` to connect surfaces into journeys.
4. Use `02-ux-state-spec/route-state-matrix.csv` for route/state ownership.
5. Compare exactly three paired desktop/mobile directions in
   `03-visual-exploration/`.
6. Record independent reviews and the selection in
   `03-visual-exploration/selection.md` before UI implementation.
7. Give implementation workers `04-ai-context/implementation-context.json`.
8. Release each finalized slice only through
   `05-handoff-qa/release-checklist.md`.

The predecessor package at `docs/workflows/v0.1-alpha-experience/` remains the
reference for the already-released first slice. This package supersedes it only
for entries explicitly recorded in the decision log.
