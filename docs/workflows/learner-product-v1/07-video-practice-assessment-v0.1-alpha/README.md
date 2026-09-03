# Video → Practice → Evidence → Review → Improve

Workstream ID: `AC-WF-LL-07`
Package version: `0.1-alpha`
Package status: **contract-ready; visual references ready; runtime/provider activation not claimed**
Prepared: 2026-09-03

This is a docs-only workflow package for the Authority Closers learner loop on
desktop Chrome and the responsive PWA boundary (iOS Safari and
Android-compatible Chrome). It defines a coherent path from a module roadmap
through approved video, authored knowledge checks, quiz/test, reflection,
implementation evidence, gated human review, and improve/retry. It leaves
app code, media providers, real calls, payment, native apps, and production
state untouched.

## Start here

1. Read [`00-start-here/experience-brief.md`](00-start-here/experience-brief.md)
   for outcome, roles, platform scope, and the canonical-vs-recovery boundary.
2. Read [`01-research-journeys/research-scan-and-source-manifest.md`](01-research-journeys/research-scan-and-source-manifest.md)
   before changing a platform or accessibility assumption.
3. Follow [`01-research-journeys/journeys.md`](01-research-journeys/journeys.md)
   for the primary loop and recovery journeys.
4. Treat [`02-ux-state-spec/state-transition-matrix.csv`](02-ux-state-spec/state-transition-matrix.csv)
   and [`02-ux-state-spec/behavioral-spec.md`](02-ux-state-spec/behavioral-spec.md)
   as the implementation-facing behavior contract.
5. Review exactly three paired directions in
   [`03-visual-exploration/direction-briefs.md`](03-visual-exploration/direction-briefs.md)
   and the selected direction decision.
6. Give future design/implementation work
   [`04-ai-context/ai-design-context.json`](04-ai-context/ai-design-context.json),
   [`04-ai-context/prompt-pack.md`](04-ai-context/prompt-pack.md), and
   [`04-ai-context/learning-loop.puml`](04-ai-context/learning-loop.puml).
7. Close the handoff using
   [`05-handoff-qa/qa-release-checklist.md`](05-handoff-qa/qa-release-checklist.md)
   and read [`05-handoff-qa/validation-report.md`](05-handoff-qa/validation-report.md).

## Package map

| Folder | Contents |
| --- | --- |
| `00-start-here` | experience brief and scope boundary |
| `01-research-journeys` | evidence/inference scan, exact controlled-source register, and journeys |
| `02-ux-state-spec` | behavioral contract and full state-transition matrix |
| `03-visual-exploration` | exactly three desktop/mobile visual directions and selection record |
| `04-ai-context` | compact AI context, prompts, and editable PlantUML source |
| `05-handoff-qa` | component contract, asset manifest, decision log, QA/release gate, validation evidence |

## Non-negotiable boundaries

- Canonical identity, authorization, enrollment, activity order, progress,
  completion, evidence, and review records remain server-owned.
- Analytics is an observation channel only. It cannot grant access, mark video
  complete, grade an assessment, or create payment/certificate state.
- `VIDEO`, captions, transcript, playback, and resume are conditional on an
  approved media policy and source. The package never pretends a provider is
  active.
- Knowledge checks and quiz/test feedback is authored and deterministic. No
  autonomous AI scoring, mastery, ranking, or reward is designed before
  AC-SVAL gates are satisfied.
- Human review is visible only from a real assigned-reviewer contract. No
  reviewer, review result, or external call is fabricated.
- Offline is read-only for canonical data. Approved local recovery copies may
  be marked unsynced, but no offline canonical write or background-submit claim
  is made.
- A responsive PWA is still a browser surface. Safe-area CSS, install prompts,
  and standalone display do not claim a native iOS/Android application.

## Authority and status

The authority order is: current user constraints; ratified legal, security,
accessibility, product, and engineering controls; exact controlled sources in
the repository register; this package's behavior/state contract; then visual
references. This package does not supersede the controlled Drive documents or
the neighboring learner-product packages. It is reference-ready, not
production-approved; browser/device, media-governance, human-review, and
AC-SVAL evidence remain release gates.
