# Learner screen-family design workflow package

Workstream ID: `AC-WF-LEARNER-SF-V0.1A`  
Package version: `0.1-alpha`  
Package status: **contract-ready; visual generation pending**  
Prepared: 2026-09-03

This is a docs-only, reproducible screen-family package for the Authority
Closers learner product. It covers the learner shell, first-value path,
learning/catalog surfaces, activity/evidence loop, progress and plans,
notifications, certificates, identity/recovery, profile/avatar, settings,
offline/session recovery, and advanced theme variants. It does not edit app
code or declare any route, provider, payment, access, score, schedule, or
runtime behavior that is not supported by the controlled source set.

## Start here

1. Read [`00-start-here/scope-and-authority.md`](00-start-here/scope-and-authority.md).
2. Review the exact-source ledger in
   [`01-research-journeys/source-manifest.csv`](01-research-journeys/source-manifest.csv)
   and the human-readable notes in
   [`01-research-journeys/source-manifest.md`](01-research-journeys/source-manifest.md).
3. Use [`01-research-journeys/flow-catalog.md`](01-research-journeys/flow-catalog.md)
   and [`01-research-journeys/screen-inventory.md`](01-research-journeys/screen-inventory.md)
   to locate stable flow and screen IDs.
4. Treat [`02-ux-state-spec/state-transition-matrix.csv`](02-ux-state-spec/state-transition-matrix.csv)
   as the machine-readable behavior contract. The prose companion is
   [`02-ux-state-spec/behavioral-spec.md`](02-ux-state-spec/behavioral-spec.md).
5. Use [`04-ai-context/ai-design-context.json`](04-ai-context/ai-design-context.json)
   and [`04-ai-context/prompt-pack.md`](04-ai-context/prompt-pack.md) for future
   visual or implementation exploration.
6. Do not call this package visually approved until the gate in
   [`03-visual-exploration/README.md`](03-visual-exploration/README.md) is closed.
7. Run `powershell -ExecutionPolicy Bypass -File .\scripts\validate-package.ps1`
   from this package directory and inspect
   [`05-handoff-qa/validation-report.md`](05-handoff-qa/validation-report.md).

## Package map

| Folder | Contents |
| --- | --- |
| `00-start-here` | scope, authority, non-goals, and handoff boundary |
| `01-research-journeys` | controlled-source ledger, evidence scan, flows, screen inventory |
| `02-ux-state-spec` | screen contracts, behavior, state taxonomy, full state matrix |
| `03-visual-exploration` | explicit visual-generation gate; no rasters generated here |
| `04-ai-context` | compact AI context, prompt pack, editable PlantUML flow source |
| `05-handoff-qa` | component contract, asset manifest, QA/release gate, decisions, validation |
| `scripts` | deterministic structural validation for JSON, CSV, IDs, routes, and references |

## Authority and status

Controlled Google Drive documents remain the long-form source of truth. This
package records implementation-facing interpretation and evidence links; it
does not supersede BRD, PRD, IA, UX State, UI, SRS, Data/Tenancy, API,
Security, Admin, Telemetry, Mobile/PWA, DevOps, QA, ADR, AC-IMP, or AC-UXA
documents. `reference-ready` means the behavior is specified and traceable;
`production-approved` requires exact-release runtime, accessibility,
security, provider, and release evidence that this package does not provide.

## Scope guardrail

No generated visual asset, Figma/Canva file, Drive upload, or Notion task is
claimed by this package. The only external connector use was read-only source
fetching by exact controlled Drive ID. Existing neighboring workflow folders
and in-progress app edits are preserved.
