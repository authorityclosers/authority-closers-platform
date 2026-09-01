# Authority Closers v0.1 Alpha experience workflow

Status: **reference-ready workflow contract; not a runtime or production approval**
Workstream ID: `AC-WF-V01-ALPHA`
Baseline date: 2026-09-01

This package defines the traceable learner and operator experience for the
browser-first Authority Closers v0.1 Alpha. It turns the approved first-slice
documents, current route implementations, the Drive UI matrix, the selected
Clarity Grid references, and accepted enrollment/profile/theme decisions into one
implementation-facing workflow. It does not assert that every screen is live.

## Start here

1. Read [`00-start-here/experience-brief.md`](00-start-here/experience-brief.md).
2. Follow the six journeys in
   [`01-research-journeys/journeys.md`](01-research-journeys/journeys.md).
3. Treat
   [`02-ux-state-spec/state-transition-matrix.csv`](02-ux-state-spec/state-transition-matrix.csv)
   as the state/action/recovery index.
4. Use [`02-ux-state-spec/behavioral-spec.md`](02-ux-state-spec/behavioral-spec.md)
   for route and screen behavior.
5. Use
   [`03-visual-contract/design-system-contract.md`](03-visual-contract/design-system-contract.md)
   for Clarity Grid, semantic tokens, responsive behavior, and theme rules.
6. Give implementation or visual agents
   [`04-ai-context/ai-design-context.json`](04-ai-context/ai-design-context.json)
   plus [`04-ai-context/prompt-pack.md`](04-ai-context/prompt-pack.md); neither
   file may override controlled behavior.
7. Render the editable flow from
   [`04-ai-context/v0.1-alpha-experience.puml`](04-ai-context/v0.1-alpha-experience.puml).
8. Release only through
   [`05-handoff-qa/qa-release-checklist.md`](05-handoff-qa/qa-release-checklist.md).

## Package map

| Artifact                                       | Purpose                                                                       |
| ---------------------------------------------- | ----------------------------------------------------------------------------- |
| `00-start-here/experience-brief.md`            | audience, boundary, outcome, authority, non-goals                             |
| `01-research-journeys/source-manifest.md`      | exact Drive IDs, local contracts, external primary guidance, provenance       |
| `01-research-journeys/journeys.md`             | primary, alternate, recovery, PWA, and admin journeys                         |
| `02-ux-state-spec/behavioral-spec.md`          | routes, screens, inputs, states, privacy, analytics, ownership                |
| `02-ux-state-spec/state-transition-matrix.csv` | machine-readable state/transition contract with stable IDs                    |
| `03-visual-contract/design-system-contract.md` | selected visual direction, components, semantic tokens, themes, accessibility |
| `04-ai-context/ai-design-context.json`         | compact machine context and generation constraints                            |
| `04-ai-context/prompt-pack.md`                 | source-attachment and screen-family prompts                                   |
| `04-ai-context/v0.1-alpha-experience.puml`     | editable end-to-end diagram source                                            |
| `05-handoff-qa/asset-manifest.json`            | source assets and package artifacts with status/provenance                    |
| `05-handoff-qa/decision-log.md`                | decisions, source basis, supersession policy, unresolved gaps                 |
| `05-handoff-qa/qa-release-checklist.md`        | structural, behavior, a11y, browser, security, and release gates              |
| `05-handoff-qa/validation-report.md`           | reproducible validation result and changed-path boundary                      |

## Stable ID rules

- Journeys: `JRN-01` through `JRN-06`.
- Stages: `STG-{DOMAIN}-{NN}`.
- Screens: approved prefixes such as `AUTH`, `ONB`, `HOME`, `COURSE`,
  `MOD`, `ACT`, `PROG`, `SET`, `SYS`, and `ADM`.
- Transitions: `TR-{DOMAIN}-{NNN}`.
- Decisions and gaps: `DEC-{NNN}` and `GAP-{DOMAIN}-{NNN}`.

The same screen ID means the same behavioral surface in every artifact. A
visual frame, implementation route, test, or screenshot must reuse that ID and
add a state suffix when needed, for example `ACT-02-save-failed`.

## Scope boundary

Included: consent-gated registration, email verification and recovery,
existing-identity Google sign-in/recovery, progressive onboarding, a distinct
public learner context, explicit consent-backed free-course start, learner
home, the published free-course overview, the Module 1
`WATCH -> REFLECT -> IMPLEMENT -> REVIEW -> IMPROVE` loop, honest progress,
profile/settings, Light/Dark/System appearance, universal recovery states,
Windows Edge/PWA and iOS Safari/PWA behavior, and a separate fail-closed admin
foundation.

Excluded: future LMS breadth, broad discovery/library, quiz, certificates as a
launch claim, billing, SSO/SCIM, tenant branding, broad notifications,
simulator/call-review engines, official autonomous scoring, real-call
processing, native Windows/iOS applications, broad B2B/enterprise features,
community, calendar, inbox, and external integrations.

## Current implementation and release status

- `GAP-ENR-001` is superseded by ADR 0028 and `DEC-014`. The exact free-course
  path requires the explicit `Start free course` action, the exact recorded
  current consent, and an active `learner` membership in the distinct active
  public learner tenant. Eligibility uses `AC-FREE-SELF-ATTESTATION-v1` and is
  committed with enrollment. Exact-current runtime proof remains pending.
- `GAP-MEDIA-001`: approved media, transcript, captions, and real playback
  evidence are not established by a UI reference.
- `/progress`, `/settings`, and device-local Light/Dark/System now have current
  repository routes/components and are `implementation_candidate` or
  `runtime_pending` as recorded per screen. This package does not claim live
  proof, account-level preference sync, or learner/admin theme sync.
- Modules 2-4 remain topology-only. No activity, completion, or unlock breadth
  is inferred for them.
- `GAP-RUNTIME-001`: this package supplies no exact-SHA staging, Edge, iOS
  Safari, mail, OAuth, media, security, load, or production runtime evidence.

Pending items block only their affected capability or proof level. They do not
authorize direct database edits, fabricated state, provider semantics, or a
broader product claim.
