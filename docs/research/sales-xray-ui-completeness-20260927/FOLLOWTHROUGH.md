# Sales Xray UI research — completed follow-through

27 September 2026. Research and handoff only. No application edits, image generation, provider calls, builds, deployments or new approvals in this batch.

## Start here

The old August BRD is excluded from decision authority by the owner's latest instruction. The [updated requirements baseline](UPDATED-REQUIREMENTS.md) captures 25 current requirements and twelve precise unresolved decisions without inheriting old defaults. It is the working Sales Xray update, not a claim that a new approved platform-wide BRD was found in Drive.

| Deliverable | What it makes concrete |
| --- | --- |
| [Updated requirements](UPDATED-REQUIREMENTS.md) | Current owner intent, acceptance evidence, authority correction, scope and outstanding policy choices |
| [Journey contracts](JOURNEY-CONTRACTS.md) | 24 transition edges across auth/workspaces, upload/admission, reviewer access and report navigation, plus route/identity ownership |
| [Evidence and data contracts](EVIDENCE-DATA-CONTRACTS.md) | All fourteen report points mapped to actual fields; graph definitions, Calls semantics, prospect groundwork and practice limitations |
| [Operations and settings](OPERATIONS-SETTINGS-CONTRACTS.md) | Configuration/test/activation, mutation uncertainty, account edits, grant recovery, notification separation, DOCX and deletion lifecycle |
| [Next design queue](NEXT-DESIGN-QUEUE.md) | Eight connected packets, 22 exact reference targets with corresponding mobile states and named missing deltas; generated versus planned status preserved |

## Corrections to the earlier audit

The prior [local source audit](LOCAL-SOURCE-AUDIT.md), [research report](RESEARCH-REPORT.md), [source register](SOURCE-REGISTER.md) and [gap matrix](GAP-MATRIX.csv) are preserved as historical audit evidence. Read the following corrections before treating their descriptions as current:

1. **G01/G02 reviewer mounting:** retained learner review components are not the active route. Learner invite and assignment pages return `notFound`; dedicated Admin `/reviewer/*` uses separate email-link reviewer authentication. Follow the mounted path documented in JOURNEY-CONTRACTS, not orphaned components.
2. **G08 return navigation:** current acquisition mounts `ReportModes`, which already implements arrival/return and section history. Legacy `CallStudio` uses `ReportExplorer` with different history semantics. The gap is parity and sequence verification, not blanket absence of Return or smooth navigation.
3. **G09 prospect groundwork:** newer untracked fact-contract work exists and is preserved. It supplies exact source/numeric/revision primitives, not persistent CRM entities, permission policy, timestamps or retention. Do not rebuild those primitives or label the complete prospect feature implemented.
4. **G06/G10 point 13:** the strict current overview requires `progress=null`. Lack of longitudinal display is not evidence that a finished chart was accidentally omitted. New progress capability needs new supported inputs and semantics.
5. **Source authority:** old BRD/plan defaults are excluded or provisional. A freshly retrieved old document is still old. Current code is observed behaviour, not future policy; an uploaded image is not completion evidence.

## Pro challenge and independent review

The existing [Report workspace redesign Pro chat](https://chatgpt.com/g/g-p-6aa868face2081919192a1393ea64826/c/6aa8d09b-878c-83e8-bc58-47cf97603b61) completed bounded follow-up **XR-CONTRACT-03**. Authority Closers Pro and Pro power 5/5 were verified before dispatch. The prompt contained a sanitized requirements/technical summary, no customer calls, credentials or raw Brain documents. It requested three questions and inline output only.

Accepted findings: classify requested direction, decisions, current implementation and recommendations separately; make identity boundaries explicit; distinguish one user action from several durable transitions; preserve unknown mutation outcomes; test actual report history and current unavailable content; avoid presenting fact primitives as live entities. Added cancellation/abandoned-upload retention, language-regeneration semantics, provider fallback and DOCX snapshot/access to the decision detail. The response's eight D identifiers are local to that response; the twelve identifiers in UPDATED-REQUIREMENTS remain canonical for this package.

Pro did not inspect the repository independently. Its HTTP accepted-processing analogy is not evidence that our delete endpoint returns HTTP 202 or has any particular cascade semantics. Its citations and recommended tests do not establish current product correctness. The source observation is narrower: the UI accepts a `deleting` state, which is not proof of completed erasure.

Independent local review verified representative provider-save/activation uncertainty, minute-grant marker recovery, delete-state and mounted-navigation references. It found no material issue in the updated requirements/settings contracts. Caveat retained: backend commit/idempotency outcomes, costs and deployed behaviour were not exercised.

## Source freshness and receipts

Pinned source HEAD: `e488f952b1aafc10761f304630965d8233a2e39b`. Agent contract files include inspected working-copy hashes. Active unrelated settings/backend/prospect changes remain untouched. The new follow-through validation records root source hashes, local link/line checks, candidate reference checks and unchanged prior-audit hashes.

Company Drive exact reads established that Master Index and BRD were August v0.5. A focused `BRD` search did not verify a newer replacement. The September source intake at `docs/plans/sales-xray-v02/source-intake.json` supplies exact IDs and earlier captured hashes for newer Brain/report/context/prospect/UX material. Those documents were not all freshly reread or adopted in this follow-through; their original focused-review limits remain.

Private captured text, browser search evidence, sanitized Pro prompt/response and completion screenshot are stored under `C:/Users/Suyash/.codex/private-artifacts/ui-completeness-research-20260927/contracts-followthrough/`. Raw controlled text is not copied into this repo handoff.

Pro prompt SHA-256: `7c975c17a5f479a010ac6ab60dbecdd19a456076b5fca59266eb4b0cab2300ac`.

Pro response SHA-256: `bb949709be786b7f396a79c43a7849d398f4d5bec4cd837d18c08a2a9b9c388a`.

## What happens next

The first proposed connected design/prototype sequence is shell → authentication → upload/recovery → Calls → report → evidence/transcript → Return. It reuses adequate existing references and adds missing states. Later packets deepen reports, settings, access and prospects as their affected data/decision contracts become ready. All acceptance checks in the package are proposed unless explicitly marked as the lightweight documentation checks performed here. Nothing in this package claims a live release or a completed new image batch.
