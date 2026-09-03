# Closers Academy Adaptive Learning North Star

> Status: WORKING STRATEGY ARTIFACT — FOUNDER-DIRECTED, NON-CANONICAL
>
> Last updated: 2026-09-03
>
> Authority: none. The controlled Drive corpus and repository guardrails remain authoritative; this file must not silently change a business rule, contract, route, event, score, provider or release gate.

## Purpose

This is a bounded wayfinding document for the learner-product workstream. It captures the intended relationship between a reusable learning platform, tenant configuration and the Closers Academy experience, then gives implementation slices that can be verified without turning strategy into an undocumented specification.

The direction below is a product hypothesis unless the relevant controlled document already states it. Where this file and a controlled source differ, the controlled source wins. Promotion of a direction into accepted behavior requires the normal decision and change-propagation path: BRD -> PRD -> IA/UX states -> UI/SRS -> data/API/event contracts -> security/QA/release evidence.

## North-star direction (non-canonical)

The product should grow as one reusable Learning & Practice Platform, with bounded configuration and product expression layered on top:

```text
Learning & Practice Platform (reusable kernel)
  -> tenant configuration (approved, bounded overlays)
    -> Authority Closers (methodology and operating context)
      -> Closers Academy (learner-facing experience and content)
```

This hierarchy is not permission to create bespoke tenant authorization, payment, entitlement, scoring, privacy or audit semantics. The platform kernel remains the place for canonical identity/context, versioned content and activities, evidence, progress/completion, policy evaluation, projections, support and governed provider boundaries. The allowed configuration surface must be defined by the controlled contracts; this file does not define configuration fields.

The useful meaning of “adaptive” here is responsive, explainable path guidance based on approved learner context and canonical learning state. It is not a claim that an ML system, autonomous scorer or competency engine is approved.

## Learner loop

The intended loop is a repeatable movement from orientation to action and improvement:

| Stage            | Learner job                                                                | Product response                                                                   | Boundary                                                                                    |
| ---------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Discover         | Find a relevant topic, path or starting point.                             | Make eligible options and their purpose understandable.                            | Do not infer a persona, level or entitlement from a click.                                  |
| Learn            | Engage with the structured content/activity.                               | Show context, prerequisites, progress and a recoverable activity state.            | Completion is not proof of mastery.                                                         |
| Practice         | Rehearse a behavior in a bounded activity.                                 | Capture the appropriate attempt/evidence and give safe, purpose-labelled feedback. | No autonomous official scoring is implied.                                                  |
| Apply            | Try the behavior in the learner’s own context.                             | Make the intended application and next reflection legible.                         | This does not activate real-call capture, recording or external AI.                         |
| Reflect          | Record what happened, what was noticed and what remains unclear.           | Preserve drafts, resume state and the evidence boundary.                           | Do not claim that an unverified real-world action occurred.                                 |
| Improve          | Name one correction or next behavior to try.                               | Turn the reflection into an actionable, methodology-grounded next step.            | No unsupported skill or readiness claim.                                                    |
| Revisit          | Return to incomplete, relevant or previously observed work.                | Offer a safe route back to the relevant activity/evidence.                         | The exact weakness/revisit policy remains a controlled contract concern.                    |
| Next Best Action | Choose the next eligible action with confidence about why it is suggested. | Explain the reason, destination and current state; retain a neutral fallback.      | Start with rules; a recommendation is not a score, credential or canonical completion fact. |

The loop is a product model, not a new activity taxonomy. The existing Program -> Module -> Activity kernel and the initial Free Course activity contracts remain the implementation authority.

### Meaningful active day (direction)

A meaningful active day should represent purposeful learning or practice, not merely opening the application, signing in or viewing a dashboard. The qualifying action should be an eligible activity attempt/completion or another explicitly approved learning action that can be measured without claiming more than the underlying evidence supports.

The exact qualifying-action set, day boundary/timezone, deduplication, privacy treatment and reporting grain are not defined here. Telemetry may measure the concept, but telemetry is not canonical progress, access, payment, completion, mastery or score state.

## Completion, evidence and mastery are different

The learner experience must keep these concepts visibly separate:

| Concept                  | Meaning for this direction                                                                                                                                                       | Must not be inferred                                                                                       |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Completion               | A configured activity/module/course requirement has been satisfied and a canonical completion decision/history can be shown.                                                     | That the learner is competent, job-ready or generally improved.                                            |
| Evidence                 | An attributable observation or submission, such as activity evidence, a response, a review or server-authoritative media evidence, retained under its applicable policy/version. | That the evidence is complete learning, or that a real-world behavior happened when it cannot be verified. |
| Mastery / skill progress | A separate, evidence-backed interpretation or progress view whose purpose, authority and comparability are defined by controlled methodology and validation.                     | A single course percentage, passive consumption signal or unsupported AI result.                           |
| Certificate              | A course-completion artifact issued only after the defined completion requirements are satisfied.                                                                                | A competency certification or official skill credential.                                                   |
| Recommendation           | A proposed next action derived from approved state/evidence and explainable rules.                                                                                               | An official score, unlock authority, credential decision or replacement for canonical state.               |

Progress surfaces should therefore distinguish completion, evidence, skill/mastery interpretation and consistency. Corrections to audit-critical completion/score history preserve the original and create an authorized superseding record; they do not erase the past.

## Recommendation path: rules before ML

### Stage 1 — deterministic, governed guidance

The first adaptive behavior should be a rule-based next-action path. It may use only signals already permitted by controlled product/data contracts, such as explicit eligibility/prerequisite state, learner context, activity state and available evidence. Each output should be explainable in learner language and point to a safe destination. If a recommendation dependency fails or no rule applies, core learning remains usable and the experience falls back to a neutral eligible path.

This stage does not establish a new score, mastery threshold, level-unlock rule or event name. Rule definitions, versioning, inputs, priority and downstream effects must be frozen in the relevant controlled contracts before implementation.

### Stage 2 — measured model assistance (later)

ML/model assistance may be considered only after there is sufficient product evidence, a documented use/permission boundary, privacy and provider review where applicable, provenance, and the relevant AC-SVAL/AI gates. A candidate model may be evaluated or run in a non-authoritative mode; it cannot silently become the source of learner access, completion, progression, official scoring or credential decisions.

## Learning event envelope and projections

The platform should use one governed, versioned learning-event envelope shape for the learning facts/telemetry that need to travel to read models and projections. Event classes and authority boundaries remain those defined by the controlled Data/Tenancy and API/MCP contracts; this file adds no event names, payload fields or identifiers.

The envelope is a feed, not a source of truth:

1. A canonical command/state change is committed according to the relevant domain contract.
2. Publish intent is recorded through the governed outbox/event path; durable jobs remain distinct from events.
3. Home, Learn, Practice, Progress, admin and analytics projections consume the versioned envelope and can be rebuilt or reconciled.
4. A projection or analytics delay cannot rewrite canonical learner access, payment, completion, evidence, score or audit history.
5. Sensitive or audit-critical corrections are append-only/superseding, with the controlled provenance and authorization requirements intact.

The acceptance target is traceable state plus explainable projection freshness, not a larger event vocabulary. Existing event-envelope, idempotency, retention, authorization and telemetry contracts govern the implementation.

## Learner information architecture direction

The north-star navigation groups learner work into five primary areas:

| Primary area | Job in the direction                                                                          | Controlled-boundary reminder                                                                                  |
| ------------ | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Home         | Orient the learner, show current status and present the next best action.                     | A projection must not masquerade as canonical state when stale or unavailable.                                |
| Learn        | Discover and complete structured programs, modules and activities.                            | Program-specific prerequisites are configuration; do not make every future program globally sequential.       |
| Practice     | Rehearse, submit or review practice evidence and feedback.                                    | Practice, assessment and official purposes remain distinct.                                                   |
| AI Coach     | Provide bounded assistance and explanation when an explicitly approved capability is enabled. | Availability, external processing and official authority are separately gated; no activation is implied here. |
| Progress     | Make completion history, evidence-backed progress and next actions understandable over time.  | Do not collapse completion, mastery/skill and consistency into one number.                                    |

Secondary destinations may include Discover, Notifications, Profile, Settings, Help/Support, Certificates, account/recovery and policy surfaces. Discover is a loop stage as well as a possible destination; exact route names, mobile placement and navigation ownership remain subject to the controlled IA/UX-state freeze. Existing learner/admin surfaces and the first-slice route contract remain the source of truth for implementation.

## Settings direction and precedence

The following are conceptual categories for a future coherent settings experience, not an accepted field schema:

- Account and security
- Learning and personalization
- Practice and coaching
- Playback and accessibility
- Notifications and communications
- Privacy and data
- Appearance

For a setting that the controlled contract explicitly marks as overrideable, the intended precedence is:

```text
platform default -> tenant configuration -> learner preference
```

The precedence is evaluated only within the allowed scope of that setting. A tenant configuration cannot invent authorization, entitlement, payment, privacy, audit or scoring behavior. A learner preference cannot bypass access, prerequisite, retention, consent, safety or other hard constraints. A setting change must not rewrite immutable content versions or historical learner evidence. Exact setting keys, edit permissions, effective-state calculation and recovery behavior require downstream IA, SRS, data/API and security decisions.

## Player UX is not media infrastructure

The learner-facing player is a UX surface inside an activity shell. It should make the current activity, controls, captions/accessible alternatives, save/resume state, evidence status and next action understandable across mobile and desktop states. It may render a projection; it does not decide canonical completion from page-open, playhead or client-only state.

Governed media infrastructure is a separate platform boundary: asset/version metadata, protected authorization, provider adapter, playback evidence policy, retention/provenance, failure/retry behavior, cost and provider-policy gates. Provider choice and activation are not decided here. The media boundary must remain replaceable without changing learner routes, activity meaning or canonical learning state.

The player and the media infrastructure therefore have separate acceptance evidence:

- Player UX: state-complete interaction, captions/controls, responsive behavior, visible progress/save/recovery status and understandable failure/support paths.
- Media infrastructure: authorized access, server-authoritative evidence, interval/replay integrity, expiry/revocation, provider failure isolation, version/retention behavior and recovery proof.

## Ordered slices and gates

The following sequence reuses the existing controlled G0-G8 capability gates. It does not create a new release plan or activate a deferred capability.

| Slice                                            | Outcome                                                                                                                                                                                                              | Acceptance/evidence gate                                                                                                                                                                                                                   |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| G0 — Engineering control plane                   | Repository/CI/environment/migration substrate, tenant/authz boundary, observability, recovery, governed event/outbox/job foundations.                                                                                | Clean setup and CI evidence; migration/recovery rehearsal; executable authn/authz and tenant-negative cases; event/job distinction; no secrets; controlled refs and acceptance cases recorded.                                             |
| G1 — IA and state freeze                         | Freeze the learner area model, activity composition, player/media boundary, settings direction, First Win/recovery states and narrow admin boundary.                                                                 | Route/state and activity contracts; acceptance cases before broad UI; locked/pending/offline/save/error/reconnect states represented; no invented business rule required to implement.                                                     |
| G2 — Walking skeleton                            | Canonical identity/context -> explicit free enrollment/access -> Program/Module/Activity -> evidence/progress/completion -> outbox/jobs -> projections -> telemetry -> one narrow admin/support view.                | End-to-end state can be reconstructed; duplicate/retry-safe writes; projections are traceable to canonical facts; admin uses authorized commands, not routine database surgery.                                                            |
| G3 — Closers Academy Free Course                 | Complete the controlled four-module learning foundation using reusable activity shells and the WATCH -> REFLECT -> IMPLEMENT -> REVIEW -> IMPROVE direction; include First Win, completion and certificate behavior. | Required activity/progression tests; content/version/history proof; draft/resume/session-expiry behavior; player evidence integrity; completion remains distinct from mastery; internal staging evidence.                                  |
| G4 — Adversarial hardening                       | Prove recovery and user trust on the slice before wider exposure.                                                                                                                                                    | Cross-tenant/authz negatives; duplicate/replay and worker retry; slow/offline/reconnect; media evidence abuse; accessibility/mobile journeys; provider degradation; backup restore and side-effect hold/reconciliation; support diagnosis. |
| G5 — Controlled proof cohort                     | Expose the foundation to the controlled 20–50-user cohort only after the relevant gates pass.                                                                                                                        | Measure completion, practice behavior, First Win, meaningful active days, abandonment, support burden, mobile QoE and recovery failures; treat results as product/operational evidence, not psychometric validity or competency proof.     |
| G6 — Paid commerce/entitlement (later gate)      | Extend the same platform with paid web commerce only after payment, entitlement and reconciliation controls pass.                                                                                                    | Independent P0 payment/entitlement, provider idempotency, audit and restore evidence; payment state never couples directly to access. Not activated by this file.                                                                          |
| G7 — AI practice/evaluation (later gate)         | Add bounded AI assistance or evaluation only through the AC-SVAL ladder and explicit privacy/provider controls.                                                                                                      | Purpose/authority/provenance, human-confirmed official outcomes until gates pass, appeals/corrections, robustness and cost evidence. Not activated by this file.                                                                           |
| G8 — WhatsApp, native apps and B2B (later gates) | Activate each capability independently when current policy, economics, privacy, tenancy and operational evidence support it.                                                                                         | Capability-specific policy/provider/tenant/release gates; no full B2B, native-store, WhatsApp or voice scope is implied for the foundation.                                                                                                |

### Evidence packet for every implementation slice

The implementation handoff for a slice should contain the smallest useful controlled references, acceptance cases, changed code/files, schema/API/event impact, tests, screenshots or machine output where useful, telemetry/security/privacy notes, deployment/rollback evidence and traceability update. “The screen works” is not sufficient evidence.

## Implementation sequencing rules

1. Reconcile the controlled source order and identify which direction is already controlled versus still a hypothesis.
2. Freeze the relevant IA, UX-state and activity contracts before broad UI work; preserve explicit loading, empty, locked, pending, error, offline and recovery states.
3. Build canonical state and tenant-safe boundaries before relying on projections, recommendations or analytics.
4. Implement the deterministic/rule-based next-action path against approved contracts; give it a safe neutral fallback.
5. Add the learner shells and player UX on top of the contracts; keep governed media infrastructure behind its adapter and evidence gates.
6. Prove the Free Course internally, then run adversarial hardening and restore/recovery evidence before the controlled cohort.
7. Treat paid commerce, autonomous/official AI scoring, real-call processing, native-store commerce, WhatsApp and scaled B2B as independent capability gates, not hidden dependencies of this north star.

## Explicit non-scope

This artifact does not:

- create or approve protected business semantics, route/screen IDs, data entities, event names/payloads, scoring classes, thresholds, recommendation formulas or provider selections;
- define ML architecture, training data, autonomous scoring, mastery/competency claims or a universal score/average;
- activate paid commerce, real-call recording/transcription, external AI processing, native-store billing, WhatsApp, voice simulation, full B2B/white-label UI or community;
- make analytics/events, a projection, a player, a tenant configuration or the VPS a canonical source of truth;
- authorize direct SQL/database edits, destructive history replacement or production state changes; or
- replace the controlled PRD, IA, UX-state, UI, SRS, data, API, security, admin, telemetry, DevOps, QA, ADR or assurance documents.

## Controlled traceability

The source register is [`docs/traceability/CONTROLLED_SOURCE_REGISTER.md`](../../../traceability/CONTROLLED_SOURCE_REGISTER.md). The exact controlled Drive references read for this artifact, in the required order, are:

1. [Master Index — `1gC6BdFZ2LfjrpjM-qPKcX1qWMTUBSAXo3b-AlaOYqus`](https://docs.google.com/document/d/1gC6BdFZ2LfjrpjM-qPKcX1qWMTUBSAXo3b-AlaOYqus/edit)
2. [Approved BRD — `1HEp7QN4u3c_636uACznnkruYHhGYHAJWXH7Dlfjybpk`](https://docs.google.com/document/d/1HEp7QN4u3c_636uACznnkruYHhGYHAJWXH7Dlfjybpk/edit)
3. [AC-IMP-00 — `10tKbAIJWONFNTzK2-NHffy4h1wKgoQP7VdJH_K2eR-A`](https://docs.google.com/document/d/10tKbAIJWONFNTzK2-NHffy4h1wKgoQP7VdJH_K2eR-A/edit)
4. [AC-IMP-01 — `1JVnCjDdE79YseM-1PuhvW00xcoicwmhoHtUvEuKKrdU`](https://docs.google.com/document/d/1JVnCjDdE79YseM-1PuhvW00xcoicwmhoHtUvEuKKrdU/edit)
5. [AC-IMP-03 — `1ncsRMiMMiQ39tCn7dV3vpqwUnirY06BgSuVdm_BuIFo`](https://docs.google.com/document/d/1ncsRMiMMiQ39tCn7dV3vpqwUnirY06BgSuVdm_BuIFo/edit)
6. [AC-IMP-04 — `1gQnsY1JjphpmOmfyCRZkfI-p0TWZjF1PkY1xF744Gnc`](https://docs.google.com/document/d/1gQnsY1JjphpmOmfyCRZkfI-p0TWZjF1PkY1xF744Gnc/edit)
7. [AC-IMP-05 — `1Vvf1wCA_JjrJQwhkTsgyDM_9179G4M899pWWc3-UdXw`](https://docs.google.com/document/d/1Vvf1wCA_JjrJQwhkTsgyDM_9179G4M899pWWc3-UdXw/edit)
8. [PRD — `1vZGxiP5GRA7He0gA7oF6hmTeHqoEZUIJko_QBUtDW_k`](https://docs.google.com/document/d/1vZGxiP5GRA7He0gA7oF6hmTeHqoEZUIJko_QBUtDW_k/edit)
9. [Information Architecture — `1VLJTswU2sqlimfoSIROVvlJ9Z6ue-6Dd45oEcu1ddhs`](https://docs.google.com/document/d/1VLJTswU2sqlimfoSIROVvlJ9Z6ue-6Dd45oEcu1ddhs/edit)
10. [UX Research — `1M_IlSgZwWfHVk1IU3JBzY-EhT3RIfXO07WII8MbwxPM`](https://docs.google.com/document/d/1M_IlSgZwWfHVk1IU3JBzY-EhT3RIfXO07WII8MbwxPM/edit)
11. [UX State Specification — `10HzU7kLk78WBHd_Y23jYaP0rIaScq7gW27e5D7D-08E`](https://docs.google.com/document/d/10HzU7kLk78WBHd_Y23jYaP0rIaScq7gW27e5D7D-08E/edit)
12. [UI Design System — `1y7yCqro9ABW8Yn61ZVmnLV8eGlelcq3BisCDTx40SsI`](https://docs.google.com/document/d/1y7yCqro9ABW8Yn61ZVmnLV8eGlelcq3BisCDTx40SsI/edit)
13. [SRS — `1qE_ASXOBN-AAuIglfs4-5Fi_HN3x-jDItBYdb95Ou2g`](https://docs.google.com/document/d/1qE_ASXOBN-AAuIglfs4-5Fi_HN3x-jDItBYdb95Ou2g/edit)
14. [Domain, Data, Event & Tenancy Model — `1SUxNYTu30NXwBEbk7os1OBVn4H5qBky-LnzLuOvwaYw`](https://docs.google.com/document/d/1SUxNYTu30NXwBEbk7os1OBVn4H5qBky-LnzLuOvwaYw/edit)
15. [API, Webhook & MCP Contracts — `1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0`](https://docs.google.com/document/d/1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0/edit)
16. [Security, Privacy, IAM & Audit — `1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw`](https://docs.google.com/document/d/1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw/edit)
17. [QA, Verification & Release Gates — `1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg`](https://docs.google.com/document/d/1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg/edit)
18. [DevOps, Environments, SRE & Observability — `1r1P2XdYSY8XhcgLR6icYqhlN1vEbqKagj8Rb16JpcJs`](https://docs.google.com/document/d/1r1P2XdYSY8XhcgLR6icYqhlN1vEbqKagj8Rb16JpcJs/edit)
19. [Admin, ERPNext & Business Operations — `12-VjN02jx8M7S8wJrZLcl4OwLcXIFGXKu74wxdJrWuY`](https://docs.google.com/document/d/12-VjN02jx8M7S8wJrZLcl4OwLcXIFGXKu74wxdJrWuY/edit)
20. [Telemetry, Analytics & AI Evaluation — `1ggdrD_ldZL3ItJsAMONq_ygQFjbR6dOURpeHGXd4M4I`](https://docs.google.com/document/d/1ggdrD_ldZL3ItJsAMONq_ygQFjbR6dOURpeHGXd4M4I/edit)
21. [ADR, Risk & Change Log — `1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY`](https://docs.google.com/document/d/1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY/edit)

Relevant assurance inputs were also read after the implementation order: [AC-UXA-01 adversarial UX/service-recovery/accessibility audit — PDF ID `19eiKLBdm5ziPsqCFZ55f8iHx0DBM43YH`](https://drive.google.com/file/d/19eiKLBdm5ziPsqCFZ55f8iHx0DBM43YH/view), [AC-SVAL-01 scientific validation framework — PDF ID `1gofD6nJn59WZy5OVBE53TCpUQlwcu1MJ`](https://drive.google.com/file/d/1gofD6nJn59WZy5OVBE53TCpUQlwcu1MJ/view), and [AC-GOV-AUD-001 policy/provider dependency audit — Google Doc/Office file ID `17Gs86tkRo4jr8XcqgMPyO-UojXeTANnY`](https://drive.google.com/file/d/17Gs86tkRo4jr8XcqgMPyO-UojXeTANnY/view).

The local learner workflow brief and README provide workstream context only; they do not supersede the controlled corpus.
