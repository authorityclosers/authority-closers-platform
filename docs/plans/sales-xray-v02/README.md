# Sales Xray standalone v0.2 — source intake and delivery contract

Status: first-release implementation in progress, 23 September 2026. The engine,
matching report UI, progress/recovery and usable Admin/CLI controls ship together.
This document does not claim v0.2 deployment or approve protected business policy.

## Starting point and timing

The preceding recovery release is the baseline for this work:

- Runtime source: `270a4b57e39646ba6b5e171614bc9ef114091d09`.
- Source plus acceptance documentation: `c8f16cb2330008ada6374663d0a7d2442aec6532`.
- [Production acceptance](../../evidence/sales-xray-reliable-20260922/production-270a-acceptance.md)
  records fresh synthetic guest and account processing, report reload, saved-call
  reopen, evidence playback and ownership isolation on the deployed release.
- A 59:58 synthetic recording passed real-provider staging processing and saved
  report playback. This is not a fresh production hour-long test, a multilingual
  quality benchmark, or proof that every possible recording succeeds.
- The user explicitly sequences this standalone expansion after the working
  production journey. That measured gate permits v0.2 intake and isolated work.
  Any newly reproduced defect blocks its affected capability, not every workstream.

The research ZIP and the Atlas Sheet use older code revisions. Their open/closed
labels cannot replace the current acceptance receipts. Reconcile findings against
the pinned baseline before carrying them into a new release.

## Product meaning

Sales Xray expands from one recording to an explicitly assembled prospect journey.
Both entry points remain useful: **Single call** and **Sales journey**. Each
recording keeps its own identity, consent, duration, transcript, evidence,
processing state and source-relative timestamps.

Three responsibilities remain distinct:

| Workspace | Question answered | Boundary |
| --- | --- | --- |
| Report | What happened in this conversation or selected journey? | Summary, strengths, breakdowns, evidence, contextual findings and a bounded next action. |
| Prospect | What is known about this buyer/opportunity? | Source-linked facts, unknowns, conflicting statements, stakeholders, commitments and the next sales action. |
| Coaching | What should this salesperson improve over time? | Private learner history, stable focus, evidence, intervention, mission, reflection and development. |

A prospect journey and a learner's coaching history are different collections.
The same learner can have calls with many prospects. A journey can eventually
involve different sellers; that does not grant them access to each other's private
coaching. Cross-user sharing remains separately governed.

## Source interpretation

The supplied [voice-note conversation](https://chatgpt.com/c/6ab28423-da78-83e8-bf61-9cda0bbf5678)
contains a cleaned Marathi/English interpretation of three notes. This intake read
that interpretation; it did not independently transcribe the original audio.
It describes single/multiple recordings, appointment setting, Zoom and follow-up,
and says the September 19 detailed report is awaiting revision. The commercial
coaching split is explicitly left for a later decision in that interpretation.

| Source layer | Engineering interpretation | Adoption state |
| --- | --- | --- |
| Brain 1 / existing five-document foundation | Constitution, communication, framework, objection/decision rules and evaluation foundations. | Preserve current runtime revision; do not overwrite history. |
| Brain 2.0 | Consolidated analyzer evidence, applicability, context and qualitative findings. | Candidate rule-pack input; conflicting numeric weights remain unresolved. |
| Brain 2.1 | Contextual reasoning through possible meanings, evidence, diagnosis and response. | Candidate reasoning rules; not eight new services. |
| September 22 overlays | Appointment-setter, presentation/Zoom and follow-up context. | Candidate applicability rules. “Brain 4” is a working spoken label, not a deployed model identifier. |
| Brain 3.0 | Persistent private learner development across relevant opportunities. | Separate stateful capability; not another prompt appended to every call. |
| Layouts and September 19 report documents | Information hierarchy, component references and proposed content. | Visual/requirements evidence; sample values do not establish policy or production facts. |

Controlled AC policy and existing approvals govern activation. A Drive document's
own “runtime rulebook” label does not approve its use in this application.

## Reusable UI architecture

Use the preferred red/black Home and Calls references as the initial visual
direction, with the repository's real AC brand asset. The Reports and Coaching
images include a teal/blue alternative; use their structure without silently
introducing a second unrelated application theme. Confirm direction through a
desktop and mobile comparison before applying it across every screen.

| Shared component | Responsibility | Existing foundation to retain |
| --- | --- | --- |
| `SalesXrayShell` | Sidebar, active destination, mobile navigation, page header and account controls. | `acquisition-shell.tsx`, `profile-menu.tsx`, authenticated/guest behavior and focus management. |
| `WorkspaceHeader` / `WorkspaceTabs` | One page title, scope, optional recording selector, subordinate navigation. | Existing report navigation and route/deep-link behavior. |
| `UploadModePicker` / `RecordingUploadRow` | Single/journey selection, per-file context, validation and authoritative progress. | Acquisition studio, source hashing, measurement and quote/consent flow. |
| `CallLibraryRow` / `JourneyLibraryRow` | Searchable summaries with ready/processing/attention states. | `calls-library.tsx` and the strict shared client; no invented list endpoints. |
| `EvidenceMoment` / `SourceCitation` | Exact quote, speaker uncertainty, recording identity and play target. | `finding-evidence.tsx`, report moments and validated citations. |
| `AudioWorkspace` / `TranscriptPanel` | One shared player, waveform, seek, transcript selection and persistent state. | `call-audio-dock.tsx`, source waveform and transcript components. |
| `FindingCard` / `FactCard` / `UnknownField` | Distinguish observation, inference, unknown and contradiction. | Existing typed report/overview parser; new schema fields require explicit versioning. |
| `JourneyTimeline` | Ordered recording membership and source-bound changes across calls. | New domain; never concatenate files into one anonymous transcript. |
| `CoachingFocus` / `MissionCard` | One private development focus and its evidence/next action. | New memory domain; single-call next steps are not longitudinal progress. |
| `EmptyState` / `CapabilityState` / `ErrorState` | Clear loading, unavailable, partial, failed and no-evidence behavior. | Existing acquisition holds/recovery semantics. |

Keep visual primitives reusable, with thin feature adapters owning their data and
permissions. A component does not fetch unrelated business data or decide access.
Extract into a shared package only when multiple product surfaces actually reuse
it; avoid a speculative universal UI framework.

The reference inventory includes 3 Home, 2 Calls, 8 Reports, 7 Prospects and 10
Coaching images. Insights and Settings folders returned no children at intake.
Representative screens and the nine-panel coaching composite were visually read;
not every image has received an individual accessibility or implementation audit.

Mockup-specific values requiring real contracts include scores, probability,
mastery percentages, revenue impact, credit counts, profile identities, CRM links,
share actions and scheduled follow-ups. Preserve useful layout space without
inventing those capabilities. The current allowance unit must not become credits
merely because an image says “4,281 / 5,000”.

## Internal contracts before engine activation

1. **Knowledge pack:** immutable source IDs/revisions/hashes, approved rule IDs,
   conflict decisions, compact compiled content, evaluator revision and promotion
   record. Editing Drive creates a candidate; it never changes accepted runs.
2. **Interaction context:** separate salesperson role, interaction purpose,
   meeting medium, sequence/date, declared versus inferred values, provenance and
   unknown. “Second call” is order; “follow-up” is purpose; “Zoom” is medium.
3. **Recording processing:** retain the tested per-recording acquisition and
   provider pipeline, immutable plans, reservation/replay controls and ownership.
4. **Journey membership:** explicit prospect/opportunity association and ordered
   versioned recording membership. Same name alone cannot merge two buyers.
5. **Journey synthesis:** inputs bind to exact completed report/transcript
   revisions and chronological evidence cutoffs. Later information can qualify a
   journey conclusion; it cannot make an earlier seller appear to know the future.
6. **Report projection:** compatible, typed, schema-versioned and source-linked.
   Missing material remains unknown. An old completed report is not overwritten
   by a new Brain, language preference or membership revision.
7. **Prospect projection:** buyer facts and uncertainties with evidence, as-of
   time and correction history; no learner weakness or private reflection fields.
8. **Private coaching:** separate person-bound observation history, relevant
   opportunity counts, one focus, interventions, outcomes and learner agency.
   No repeated-pattern or mastery claim from one call.
9. **Evaluation/promotion:** frozen synthetic and consented labelled fixtures,
   qualitative semantic checks, reviewer disagreement and regression comparison.
   Citation validity alone does not establish the truth of generated prose.

These are logical responsibilities. Reuse the current API/worker/storage
boundaries unless measurement or ownership requires a separate service.

## First release: engine and report workflow together

The user explicitly superseded a shell-first release. The first v0.2 release is a
working single-call engine/report upgrade with matching reusable UI, not a visual
preview. The [product decision](https://chatgpt.com/c/6ab28423-da78-83e8-bf61-9cda0bbf5678)
and [visual handoff](https://chatgpt.com/c/6ab370c0-f420-83e8-b04b-f90cef176297)
are proposals verified against local source; neither establishes runtime success.

| Workstream | First-release result | Acceptance |
| --- | --- | --- |
| Reliability | Preserve recovered upload/report flow; fix reproduced activation replay and current-cap reservation defects. | Database replay, concurrency and effective-budget regressions. |
| Qualitative engine | Immutable ten-rule pack covering evidence, contradiction, context, objection diagnosis, relevant discovery, commercial-state honesty, modality limits and focused this-call coaching. | Source adoption, frozen prompt/plan provenance, old revision compatibility; no official numeric scoring. |
| Report contract and language | Source-bound Report, point-in-time Prospect and this-call Coaching views; English, Hindi + English and Marathi + English report modes. | Strict schemas, original quotations unchanged, unsupported legacy fields explicitly unavailable; new preference never regenerates a saved report. |
| Report UI | Dipak-derived reusable header, conclusion/outcome, strengths/improvements, evidence moments, skill and next-step components with one audio controller. | Actual desktop/mobile image reference and render comparison; keyboard, long content, zoom, reduced motion and playback. |
| Progress and recovery | Useful truthful upload-to-analysis status, saved-work visibility, clear current stage and supported leave/recovery guidance. | Long silent waits, C4 partial completion, offline/reconnect, stale polling, switched submission, reload and accessibility. No timer-derived percent or fabricated ETA. |
| Admin and CLI | Shared validated versioned settings, effective values and inspectable history; clear draft/save/activation meaning. | Authority, validation and parity tests; immutable audit history and no operational direct SQL. |
| Release | Exact-source staging acceptance then production rollout with rollback and synthetic guest/account verification. | CI/artifact identity, provider/consent controls and remaining approved test ceiling. |

The [separate progress research](https://chatgpt.com/c/6ab376e7-7ffc-83ee-9be8-e40c7d19a2c9)
examines primary HCI/psychology evidence, algorithms and recovery before the visual
implementation. Its research claims require source checks; its artifact tests must
be reproduced locally. Research runs alongside known fixes.

Later increments add explicitly linked prospect journeys, multi-recording synthesis
and persistent private coaching after their membership/privacy/policy contracts.
They are not a reason to defer the report structure needed by this first engine
release. The broader component catalogue below preserves those future boundaries;
it is not a claim all those features ship now.

Do not include full CRM, automatic WhatsApp/email sending, voice mock calls, visual
Zoom evaluation or a new billing model as incidental work. Audio-only input cannot
prove slide quality, eye contact or a meeting's future attendance.

## Decisions that source material cannot approve

| ID | Concrete decision | Bounded interim behavior |
| --- | --- | --- |
| V02-D01 | Exact adopted knowledge pack and source precedence, including the revised report when supplied. | Preserve current pack; compile/review candidates without activation. |
| V02-D02 — user direction received | English throughout the app interface; report choices for English, Hindi with English terms, and Marathi with English terms. | Hindi/Marathi prose uses Devanagari; natural code-switching is allowed, original evidence quotations stay unchanged, and the contract supports later language additions. |
| V02-D03 | Final weights, numeric evaluation and calibrated mastery policy. | Qualitative evidence only; no 95-to-100 silent normalization or automatic “80% mastered” badge. |
| V02-D04 | Coaching free/paid products and entitlements. | Preserve current access; no inferred charge or upgrade gating. |
| V02-D05 | Cross-user buyer handoff and private learner visibility. | Keep existing ownership; private coaching does not inherit prospect/report sharing. |
| V02-D06 | Journey recording/count/duration limits and quote/cancellation semantics. | Current public per-file limit remains 32 MiB and 60 minutes; no new aggregate allowance inferred from project approval. |
| V02-D07 | Authoritative attendance, deal outcome and completed-follow-up event sources. | Observed conversation and suggestions only; no invented confirmed event. |

The older assessment has twelve proposal decisions; these seven group their
release-relevant dependencies without marking the original decisions approved.
Unavailable videos/templates remain unavailable, and broader optional products
remain outside the first implementation increments.

### Language direction received during intake

On 23 September the user clarified that the app interface, layouts and controls
stay English. Generated report content may use natural Hindi/English and
Marathi/English code-switching; explicit Hindi and Marathi report options should
retain English words in English script. This supersedes the source draft's
Hindi-only report direction. It is not permission to translate or rewrite quoted
evidence. Keep schema keys, IDs, enums and provenance language-independent.

Initial selectable report modes: English, Hindi + English, Marathi + English.
English is the compatibility default when no report preference is supplied;
persist the chosen report mode into the accepted analysis revision. Changing a
preference cannot silently regenerate or charge for an existing report. Other
languages remain extensible, with their own quality fixtures before support is
advertised. Test negation, money, names, dates and mixed-script typography in each
supported report mode; display translation separately from verbatim evidence.

## Acceptance matrix

- Existing guest/account single-call path survives the shell, including restored
  sessions, new-call navigation, reload, saved-library reopen and evidence playback.
- At 390×844 and a declared desktop viewport, essential actions/status remain
  readable; dialogs/tabs/menu focus, keyboard, reduced motion and long text work.
  Do not equate no horizontal overflow with a complete one-viewport proof.
- Short, 60-minute boundary, multilingual, noisy/overlapping and no-sale fixtures
  test provider behavior and semantic fidelity separately. A synthetic passing
  report is not a claim of measured real-world accuracy.
- A source edit, model change, new language or new pack does not mutate old reports.
- Setter/closer/follow-up obligations are contextual; unobserved does not mean poor.
- Missing budget/name/outcome stays unknown. Contradictory statements preserve both
  sources. Audio references keep per-recording timing and identity.
- Journey tests cover duplicate files, reordered inputs, partial completion,
  failed members, no unintended reprocessing, two same-name prospects, temporal
  leakage, retention expiry, deleted members and unauthorized readers.
- A journey's “complete” state requires its declared membership/revision to be
  complete. One available member report does not establish aggregate completion.
- Coaching tests distinguish isolated observations, relevant repeated evidence,
  learner self-report, prompted performance, independent behavior and severity.
  Manager/prospect access alone never unlocks private reflections or missions.
- No fabricated scores, progress, revenue, assets, notifications or successful
  external actions are shown to fill a mockup.
- Each released increment carries exact source/CI/artifact identity, rollback,
  staging evidence and production acceptance. Provider tests remain bounded by the
  existing explicit budget and consent controls.

## Evidence and coverage

The intake privately retains a hashed archive inventory, captured source text,
layout metadata and an orchestration ledger. Raw source text and research prompts
are kept outside Git. The ZIP SHA-256 is
`43d206b36f631bb11de1051d01b5e3bf7a01bd39a2c2e7bba47f28b3a06a14b3`.
Its 17 entries passed path, regular-file, size and expansion checks before
extraction. Its 50 requirements, 24 packages, 12 decisions and 24 acceptance gates
are proposals from 22 September; “NOT RUN” statements are historical package
status, not fresh tests of the recovered branch.

The Brain documents received focused semantic review, not sentence-level adoption
or complete evaluation of the entire knowledge dump. The separate normal Pro research packets
receive bounded, non-overlapping questions and artifact requests. Their handoffs require local
verification and cannot approve business policy or establish deployment by claim.
