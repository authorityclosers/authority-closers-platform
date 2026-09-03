# Instructor and AC Admin workflow architecture package

Workstream ID: `AC-WF-INSTRUCTOR-ADMIN-V0.1`<br>
Package version: `0.1-alpha`<br>
Package status: **reference-ready; implementation and visual approval blocked**
Prepared: 2026-09-03

This is a docs-only workflow and UI architecture package for two future
surfaces on the Authority Closers platform:

- **Instructor Studio** — a proposed product label over the controlled
  `Content Manager` and `Coach / Reviewer` role capabilities. “Instructor” is
  not a canonical authorization role in the controlled Admin specification;
  the mapping must be approved before implementation.
- **AC Admin** — the controlled product control plane at
  `admin.authorityclosers.com`, with narrow operations for people, catalog,
  learning operations, assessment review, media, audit and system health.

The package deliberately stops at workflow/UI architecture. It does not add
application code, API implementations, database changes, route handlers,
provider integrations, B2B UI, native-store UI, billing, scoring, moderation,
learner counts or publication policy beyond what the controlled sources state.

## Start here

1. Read [`00-start-here/scope-and-authority.md`](00-start-here/scope-and-authority.md)
   for the authority order, boundary and blocked behavior register.
2. Read [`01-research-journeys/source-manifest.csv`](01-research-journeys/source-manifest.csv)
   and [`01-research-journeys/research-scan.md`](01-research-journeys/research-scan.md)
   for exact Drive IDs, revisions and evidence/inference separation.
3. Use [`01-research-journeys/screen-inventory.csv`](01-research-journeys/screen-inventory.csv)
   for stable IDs and route status.
4. Treat [`02-ux-state-spec/state-transition-matrix.csv`](02-ux-state-spec/state-transition-matrix.csv)
   as the machine-readable state contract; its companion is
   [`02-ux-state-spec/behavioral-spec.md`](02-ux-state-spec/behavioral-spec.md).
5. Review the text-only responsive references in
   [`03-visual-exploration/responsive-reference-wireframes.md`](03-visual-exploration/responsive-reference-wireframes.md).
   They are not branded or production-approved visuals.
6. Use [`04-ai-context/ai-design-context.json`](04-ai-context/ai-design-context.json),
   [`04-ai-context/prompt-pack.md`](04-ai-context/prompt-pack.md) and
   [`04-ai-context/instructor-admin-workflow.puml`](04-ai-context/instructor-admin-workflow.puml)
   for future design exploration.
7. Run `powershell -ExecutionPolicy Bypass -File .\scripts\validate-package.ps1`
   from this package directory. Results and remaining gates are recorded in
   [`05-handoff-qa/validation-report.md`](05-handoff-qa/validation-report.md).

## Package map

| Folder | Contents |
| --- | --- |
| `00-start-here` | scope, authority and approval boundary |
| `01-research-journeys` | exact source ledger, research scan, workflows and screen inventory |
| `02-ux-state-spec` | route contract, state taxonomy, behavioral specification and CSV state matrix |
| `03-visual-exploration` | visual gate and responsive text wireframes; no raster assets |
| `04-ai-context` | compact AI context, prompt pack and editable PlantUML workflow |
| `05-handoff-qa` | component/tokens contract, manifests, decision log and QA/release gate |
| `scripts` | deterministic structural validation only; no application code |

## Authority and status

Controlled Google Drive documents remain the long-form source of truth. This
package records a bounded implementation-facing interpretation and does not
supersede the Master Index, BRD, PRD, IA, UX States, UI System, SRS,
Data/Tenancy, API/MCP, Security, Admin, Telemetry, Mobile/PWA, DevOps, QA,
ADR/Risk, AC-IMP, AC-UXA or AC-SVAL documents.

`reference-ready` means that roles, routes, states, transitions, recovery
ownership and blocked boundaries are documented. `production-approved` would
require implementation, current authz/tenant tests, accessibility/device
evidence, provider/policy review and release-gate evidence that this package
does not provide.

## Connector and visual limitation

The only external connector use for this package was read-only Google Drive
fetching by exact IDs from the repository manifest. No Figma, Canva, Lucid,
Drive-upload or Notion artifact is claimed. The requested Antigravity/Gemini
ideation attempt was made but the installed client returned an ineligible
client error; no model output is used as a source of truth.
