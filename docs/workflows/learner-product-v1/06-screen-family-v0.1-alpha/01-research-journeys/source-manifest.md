# Source manifest and research evidence

Observed: 2026-09-03. The controlled Google documents were fetched through
the Google Drive connector by exact ID in the repository-mandated order. The
machine-readable ledger is
[`source-manifest.csv`](source-manifest.csv). No filename search, Drive upload,
or source rewrite was used.

## Authority order

1. Explicit current user decisions.
2. Law, platform policy, security, privacy, accessibility, and engineering
   invariants.
3. Exact controlled Drive documents in `source-manifest.csv`.
4. Current repository contracts and traceability records.
5. This package’s behavior/state contract.
6. Visual references, only after behavior is fixed.

## Read evidence, not just titles

The required-first sources establish the implementation boundary: the learner
slice is the permanent Activity-kernel foundation; free enrollment is a
controlled path; progress/evidence are canonical server state; analytics is
not authority; and P0 findings block only the affected capability. The
product/UX sources establish mobile-heavy, time-poor learners, a clear next
action, visible hierarchy, sequential required activity order within a
program, and a three-layer state model for presentation, canonical domain
state, and recovery ownership.

AC-UXA-01 was fetched as the relevant assurance input for learner recovery and
accessibility. It requires per-activity offline/draft behavior, domain-specific
pending/processing states, safe session-expiry return, captions/transcripts
where applicable, non-color status, focus management, and comfortable touch
targets. These are release criteria, not claims that this docs package or the
current runtime passes them.

## External guidance used narrowly

- [WCAG 2.2](https://www.w3.org/TR/WCAG22/) and [Target Size Minimum
  (2.5.8)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum):
  use a non-color status treatment, visible focus, reflow/zoom checks, and
  target-size compliance. AC’s comfortable learner target is approximately
  44 CSS px where practical; WCAG’s exact success criterion and exceptions
  remain the normative test.
- [MDN `prefers-color-scheme`](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/%40media/prefers-color-scheme)
  and [`color-scheme`](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/color-scheme):
  System follows the device preference; Light/Dark/System remain local
  presentation choices and must not alter product authority.

These sources refine accessibility and browser QA only. They do not override
controlled AC business, access, progress, scoring, privacy, or provider rules.

## Evidence versus inference

| Kind | Evidence | Design consequence |
| --- | --- | --- |
| Controlled fact | `/home`, `/learning`, `/discover`, `/progress`, `/settings`, activity, certificate, and offline areas are represented in the current route/contracts or source specs. | Give each a stable screen ID and state coverage; mark route candidates where IA is silent. |
| Controlled fact | Learner UX is mobile-first and outcome-driven; “next action” beats a generic dashboard. | One dominant action per ready state; keep shell navigation consistent. |
| Controlled fact | Progress and completion are canonical server-owned facts; analytics is lossy/secondary. | Label unavailable/stale distinctly from zero; telemetry rows never mutate facts. |
| Controlled fact | Free Course module order and required activity prerequisites are program configuration, not a global LMS rule. | Show locks with exact safe reason; do not invent cross-program sequencing. |
| Controlled fact | Light/Dark/System remain device-local theme mode choices; named presets and accent, density, and motion are browser-local presentation variants. | Provide the advanced appearance controls while keeping every value outside account, tenant, and authority state. |
| Controlled fact | AC-UXA-01 requires recovery ownership below founder level for routine cases. | Every retry/expiry/offline/error row names the safe learner action and support boundary. |
| Design inference | Plan horizons improve orientation when sourced by a canonical plan projection. | Provide Today/Week/Month containers; if no plan data exists, show honest empty/unavailable states rather than dates or promises. |
| Design inference | Profile/avatar crop is useful but mutation is sensitive and provider-dependent. | Specify a local preview and explicit server processing/supersession states; do not claim upload is activated. |
| Design inference | A notification center can organize authoritative read state and informational deep links. | Keep delivery preferences separate from learning/progress/access facts. |
