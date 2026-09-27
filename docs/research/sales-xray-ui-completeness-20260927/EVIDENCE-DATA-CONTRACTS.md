# Evidence and data contracts for the next Sales Xray UI batch

27 September 2026 · research follow-through for G05–G10 · no product code changes.

## Authority and evidence boundary

Inspected checkout: `C:/Users/Suyash/.codex/worktrees/sales-xray-v02-core-release-20260925/authority-closers-platform`, HEAD `e488f952b1aafc10761f304630965d8233a2e39b`. References below are repository-relative exact file/line anchors in that checkout. The hash inventory records working-copy bytes, including the new, untracked prospect contract.

The owner's latest instruction says the old BRD must not determine this work. Accordingly, old plans and the prior audit are historical/provisional context, not newly approved product policy. Current source establishes what code represents; it does not establish deployed behaviour, product authority, or current controlled-source approval. The parent lane is locating updated source. Protected decisions listed below remain unresolved until reconciled with that source and the owner's current intent. Existing non-negotiable privacy, source-fidelity and audit-history guardrails remain in force.

Read [RESEARCH-REPORT.md](RESEARCH-REPORT.md) and [LOCAL-SOURCE-AUDIT.md](LOCAL-SOURCE-AUDIT.md) first. This document makes their data questions concrete and corrects the G08 mount interpretation. It is not an endpoint specification, retention policy, database migration or approval to enable a proposed capability.

## What this audit changes

1. The fourteen-point overview already has a strict, versioned adapter. The missing deliverable is an explicit coverage and fallback matrix, not fourteen invented response fields.
2. Point 13 deliberately cannot show longitudinal progress: `overview.progress` accepts only `null`. That is a capability boundary, not a zero or an empty score.
3. Calls already has estimated-duration bars and paginated status filters. Global search, totals and measured-duration analytics are not in its inspected projection.
4. The current acquisition report uses `ReportModes`, which already implements animated arrival and Return. Legacy `CallStudio` uses `ReportExplorer`, whose browser-history behaviour differs. Do not rebuild current return controls based only on the older component.
5. The untracked prospect value contract is a useful fidelity foundation. It has no Person/Business/Opportunity identity, source timestamp locator, storage, permissions, taxonomy or deletion policy. Its existence cannot make Prospects a live CRM.

## G06 · report identity and fourteen-point presentation

### Current containers and bindings

| Input / source | Present contract | UI consequence and next acceptance condition |
|---|---|---|
| `app/report-contract.ts:58` | `SalesReport` carries findings, optional overview, dimensions, source hash, transcript revision and draft review status. | Bind all cards to this validated report; do not combine fields from different runs to make a fuller screen. |
| `app/report-contract.ts:665` | Acquisition envelope schema `ac.sales-xray.report-envelope/2` binds submission, recording, run, source hash and transcript revision. Projection is `ac.sales-xray.report-access/2`; `numeric_publication` must be false. | Keep envelope identity in the view adapter. A report name is not identity. Saved recovery metadata is not human approval. |
| `app/report-contract.ts:438` and `:628` | Legacy `report_sections` requires nine numbered descriptors. Projected reports instead receive an empty metadata list. | These nine descriptors are not the fourteen rendered points. Do not fabricate five extra descriptors or reject valid projections solely because this array is empty. |
| `app/overview-contract.ts:63` and `:105` | Optional whole overview, but if present it is strict `dipak-14-point-v1`. Known nullable fields differ from absent legacy overview. | Adapter must preserve “legacy overview absent”, valid empty collection, valid null and invalid payload as distinct states. |
| `app/report-contract.ts:293` and `:632` | Evidence requires segment identity, quote and in-range times; quote must be contained in the bound transcript. Overview evidence additionally requires the exact segment timing. | Retain exact quote and source precision; display `mm:ss` without rounding the seek identity. Passing validators does not prove that the clip contains the full useful question/reply context. |
| `app/acquisition-studio.tsx:939`, `:3117` | Report-language label is recovered from the saved plan and shown only when its report run matches. | Do not infer saved language from current settings. A display preference must not silently regenerate or translate source quotations. |

Here and in subsequent tables, the `app/` prefix means `apps/sales-xray-web/app/`.

### Field-to-point crosswalk

The navigation inventory is at `app/dipak-overview.tsx:382`; rendered points begin at `:898`. Multiple priority points come from one ordered findings list, so a two-improvement report must not invent a third improvement merely to fill point 04.

| Point | Actual data path and mapping | Evidence / absence / honest fallback |
|---|---|---|
| 01 · What you are already good at | `strengths[]`; `overview.strength_details[]` joins by `finding_index`, adds `why_it_matters` (`overview-contract.ts:126`; `dipak-overview.tsx:904`). | Finding evidence stays attached. Missing legacy detail falls back to the saved finding; no supported strength is an explicit empty state. |
| 02 · First improvement | `improvements[0]`; matching `overview.improvement_details[0].finding_index` (`overview-contract.ts:133`; `dipak-overview.tsx:939`). | `what_happened` has source evidence; replacement behaviour and why-it-matters are advice. `business_impact` is explicitly insufficient data, not calculated ROI. |
| 03 · Second improvement | Same ordered map for `improvements[1]`, if supplied. | Do not fill absent entries with generic advice. Preserve priority order; the numerical label is presentation order, not a severity score. |
| 04 · Third improvement | Same ordered map for `improvements[2]`, if supplied. | Same absence rule. Parser requires matching detail coverage for supplied improvements, not exactly three improvements. |
| 05 · Golden moments | `overview.golden_moments[]` indexes a strength and its evidence; adds `why_effective` (`overview-contract.ts:149`; `dipak-overview.tsx:368`). | Legacy fallback uses up to three evidence-bearing saved strengths and labels that provenance. A repeated source excerpt is not another independent success. |
| 06 · Missed opportunities | `missed_opportunities[]`; optional matching `overview.missed_details[]` adds prospect signal, closer response, follow-up and potential impact (`overview-contract.ts:161`; `dipak-overview.tsx:1046`). | Both signal and response are source notes. Missing extended detail uses the saved finding. “Potential impact” is not observed impact or a money estimate. |
| 07 · What the prospect may have meant | `overview.prospect_interpretations[]`: source note, possible concern, `interpretation_kind=inference` (`overview-contract.ts:177`; `dipak-overview.tsx:1087`). | Always an interpretation to check, not a fact about the person. Missing detail stays unavailable; never move it into a prospect fact without a separate reviewed fact contract. |
| 08 · Rewatch list | `overview.rewatch[]`, max three, each one evidence item with purpose `must_watch/watch/repeat` (`overview-contract.ts:189`; `dipak-overview.tsx:358`, `:1120`). | Legacy fallback chooses one distinct clip per improvement/missed/strength category, preserving report order. Contextual playback is assembled separately; a short valid quote alone does not certify a complete coaching clip. |
| 09 · Conversation change | Nullable `overview.conversation_change`: before/change/after source notes, possible effect, inference flag (`overview-contract.ts:197`; `dipak-overview.tsx:1307`). | Parser checks chronological separation. UI must label possible effect as inference, not causal proof; null states that no change sequence was established. |
| 10 · Sales skills | Eight `dimensions[]`, each with ID, label, status, observation, citations and optional evidence (`report-contract.ts:351`). Overview currently selects observed, nonblank observations (`dipak-overview.tsx:321`, `:1359`). | Other statuses are `insufficient_evidence/not_applicable/conflicted/unknown`, not zero. Historical optional evidence can be absent; retain that distinction. No numeric radar score from counts. `ethics_notes[]` remains a separate human-review note near this point, never a verdict. |
| 11 · Next-call focus | First improvement plus nullable `overview.next_call_focus`: index 0, behaviour and target (`overview-contract.ts:214`; `dipak-overview.tsx:1418`). | Legacy fallback uses the first improvement's explanation. This is report-derived advice, not a learner's saved commitment or prospect's agreed next step. |
| 12 · Personalized practice | Nullable `overview.practice`: index 0, instructions and success condition (`overview-contract.ts:222`; `dipak-overview.tsx:1449`). | The parser pairs practice/focus with the presence of improvements (`overview-contract.ts:277`). It does not store completion. Missing legacy practice is explicit. |
| 13 · Across-call pattern | `overview.progress` is forced to `null` (`overview-contract.ts:234`); view always explains no comparable multi-call history (`dipak-overview.tsx:1492`). | No trend, improvement claim, score or streak. New multi-call capability needs a new approved input/schema and deliberate comparable history. |
| 14 · Final verdict | `overview.final_assessment` repeat/fix-first/next-focus/assessment, with fallback `verdict` and first improvement (`overview-contract.ts:235`; `dipak-overview.tsx:1499`). | Diagnosis/outcome source notes remain separately inspectable. Report review status stays draft. Language simplicity and sales usefulness need human comprehension review, not parser success alone. |

Cross-field validation already requires unique, in-range references; complete detail coverage for strengths and improvements; unique golden/rewatch references; and ordered change evidence (`app/overview-contract.ts:250`). Reuse those rules rather than weakening them for richer visuals.

Minimum new fixture rows: projected v1 overview; legacy overview absent; one/two/three priorities; empty strengths; no-sale/unclear outcome; null conversation change; optional dimension evidence absent versus validated empty/observed violation; guest withheld counts; changed transcript/run binding; long English/Hindi/Marathi explanation with original quote preserved. These are proposed verification cases, not tests executed here.

## G07 · chart definitions: present artifacts versus proposed metrics

| Visual | Available source / status | Defensible meaning | Required additional definition before a richer claim |
|---|---|---|---|
| Report duration | `Transcript.duration_ms` with source hash/revision/timebase (`app/report-contract.ts:188`). Present typed artifact. | Length on that transcript/source binding. | Display approximate versus measured when mixing any other duration source; never substitute admitted minutes. |
| Saved Calls duration bar | `LibrarySubmission.durationSeconds` (`app/acquisition-client.ts:40`); current bar normalizes against longest loaded estimate (`app/calls-library.tsx:591`). Present UI. | Approximate admitted length of that call, relative only to currently loaded estimates. | Server measured-duration field and total-query contract before total-time analytics. |
| Selected evidence timeline | Finding evidence has segment, quote, start/end (`app/report-contract.ts:29`). Data available for a proposed shared map. | Where selected, validated saved findings cite the conversation. | Dedup key includes source/revision/segment/time; identify selected evidence coverage. Neither count nor density is skill, attention or sales quality. |
| Audio level / pitch | `ac.sales-xray.measurement-view/1`, C1 AudioAtlas native profile; physical channel `dbfs/f0_hz` series and null samples (`app/measurement-contract.ts:80`). Present parser and `RecordingMeasurements` component. | dBFS/Hz on decoded-audio time, per physical channel. Pitch available fraction is measurement coverage. | Do not label a physical channel as seller/buyer without an independent approved mapping. Pitch is not confidence, emotion, intent or competence. |
| Speaker interval / talk-time visualization | Transcript has nullable `speaker_id` and timed segments (`app/report-contract.ts:180`). Candidate derivation, no inspected canonical talk-time aggregate. | At most, labelled transcript segment intervals from the bound revision. | Specify treatment of silence inside a segment, overlapping speech, gaps, unknown speakers, channel alignment and whether denominator is full duration or union of voiced intervals. Segment durations alone cannot truthfully promise exact speaking time. |
| Word count / question count | Transcript text exists. Proposed versioned deterministic or analysis-derived artifact. | Text token/question counts under an explicitly named algorithm and language, if implemented. | Define punctuation/interrogative handling, multilingual tokenizer, partial transcription and revisions. No claimed current implementation from this audit. |
| Objection/change map | `objection_analysis[]` and nullable before/change/after notes exist. | Locations of the particular saved findings; interpretation visibly labelled. | No unsupported total-objection, conversion-probability, emotional trajectory or causal revenue metric. |
| Qualitative skills graphic | Dimension statuses/observations exist, numeric publication false. | Accessible evidence/status matrix with unknown/conflict retained. | Official scores/radar axes need separate approved scoring validation; do not convert citations, text length or clip count into a scale. |
| Cross-call progress | Explicitly unavailable in current overview. | Honest explanation of unavailable comparable history. | Deliberate learner/source association, comparable evidence and approved interpretation before any progress artifact. |

The measurement parser pins recording/hash, decoded-audio clock, source and decoded rates, one or two physical channels, duration, checkpoint hashes, window 40ms/hop 10ms and ordered display samples (`app/measurement-contract.ts:87`). It explicitly requires container/video sync uncertified and SignalLab unavailable (`:112`). Display samples are capped at 1,200; absence/null must break the plotted line, not interpolate certainty.

The existing chart exposes a range control and spoken time/value (`app/recording-measurements.tsx:101`), fetches saved measurements only after expansion and validates recording/hash (`:227`). It is mounted in legacy `CallStudio`'s Sound panel (`app/call-studio.tsx:2139`). This source does **not** prove AudioAtlas is shown in every current acquisition report, that measurements feed C4/C5, or that any endpoint is live today.

Every new chart handoff should name: artifact schema/revision; source/timebase; allowed identities; formula and units; denominator; coverage/unknown/overlap treatment; sample aggregation; permission/revocation behaviour; keyboard/list equivalent; source action; and as-of meaning. If one is missing, label the visual proposed, rather than generate a convincing “measured” success state.

## G05 · Calls fields, queries and recovery

| Concern | Current source fact | Next UI contract / bounded acceptance |
|---|---|---|
| Row identity | Projection has submission ID, created timestamp, positive estimated duration, nonempty state, report flag and optional name/revision (`app/acquisition-client.ts:357`). | Stable submission identity through rename, progress refresh and report reopen. Do not infer a prospect or salesperson from display name. |
| Pagination | At most 20 rows per page; `next_cursor` UUID or null. No total, query term or sort descriptor in inspected response. | Show loaded count; `+` while more may exist. No “all results” until known terminal cursor. Preserve known rows after next-page failure. |
| Status filtering | Client `callTone` derives report-ready/active/attention/idle (`app/calls-library.tsx:69`); filter applies loaded rows (`:588`, `:882`). | Say “loaded calls”; an empty filter with a non-null cursor is not proof no match exists. No business-stage inference from processing state. |
| Search / advanced sort | No such query or UI observed in inspected Calls component. | New loaded-name search may be a separately implemented limited feature; global search needs server fields, permissions, ordering, cursor/query stability and totals settled first. Do not present an unimplemented search as existing. |
| Length comparison | Approximate label “About”; longest loaded estimate is the denominator (`:38`, `:49`, `:591`). | A bar may change when longer calls load; do not imply a fixed maximum or exact audio fraction. No total measured minutes from these values. |
| Load more | Same cursor response and duplicate submission IDs are rejected; timed-out request can be retried (`:461`, `:495`). | Exercise cursor loop, duplicate row, stale/expired access and response loss. Do not drop existing rows or open a duplicate identity. |
| Rename | Confirmed label updates only its own row (`:562`); component passes name and revision to `renameCall` (`:619`). | Keep draft/conflict distinct from saved name. If future name search is active, define whether a renamed nonmatching row exits immediately or after confirmation, and preserve return/focus. |
| Refresh / identity | Processing refresh is visibility-aware at 15s (`:448`); request generations and identity guard mutation. | Keep selected filter/location and confirmed content on transient failure; reset protected view on identity loss/change. Freshness marker requires an actual confirmed read, not elapsed animation. |

Recommended state set: initial loading; loaded+more; terminal loaded; empty collection; empty loaded filter+more; next-page pending; next-page retry; duplicate/cursor verification error; stale read; rename draft/pending/conflict/confirmed; report reopen/return; access expired/changed. Reuse existing state references where they already represent these distinctions.

## G08 · mounted navigation is already richer than the older helper

| Entry | Actual mount | Source behaviour | Remaining evidence needed |
|---|---|---|---|
| Acquisition report | `app/acquisition-studio.tsx:3158` → `ReportModes` | Uses actual panel IDs, including transcript; source-bound URL parser (`app/report-modes.tsx:64`). | Desktop/mobile keyboard sequence on the exact deployed build; not another screenshot of an inert tab row. |
| Acquisition section jump | `app/report-modes.tsx:516` | Section changes push history; view-only changes replace. Arrival focuses target, scrolls with reduced-motion support and applies a temporary cue (`:490`). | Back/Forward, deep link, mode switch, nested scroller, dock offset and manual-scroll cancellation. Preserve audio position. |
| Explicit Return | `app/report-modes.tsx:200`, `:604` | Remembers element, URL and number of pushes; restores origin or safely stops if detached. Single pushed jump can use history Back. | Call/report replacement, permission loss, closed origin disclosure and element unmount must not restore stale protected context. This is in-memory DOM state, not a durable bookmark across reload. |
| Legacy report | `app/call-studio.tsx:1998` → `ReportExplorer` | Section changes replace state, intentionally keeping browser Back on the previous page (`app/report-explorer.tsx:74`). | Define product parity or intentional difference per entry. Do not silently change history in one route to match a mockup of another. |

`report-navigation.ts`'s fixed section list omits transcript, but acquisition does not use that helper: `ReportModes` reads actual panels. Therefore this audit does **not** report a current acquisition transcript-navigation bug. G08 is now a route-parity and sequence-proof task, with existing mechanisms to reuse.

Recommended test sequence: Calls row → report overview → review point 14 → source moment → pause → transcript → Return → switch Reading/Sections → Back/Forward → reopen same call. Repeat with another call/revision and permission loss. The return target, selected source and playing media must always belong to the bound call; no resume from a revoked source. These are acceptance requirements, not passed browser results.

## G09 · complete supplied prospect detail without an invented CRM

### New working-copy foundation

`packages/python/ac_platform/conversation_intelligence/prospect_fact_contract.py` is untracked in this checkout. Its module docstring explicitly excludes extraction, authorization, retention, persistence and business semantics (`:1`). The companion evidence document makes the same boundary explicit (`docs/evidence/20260926_SALES_XRAY_PROSPECT_FACT_CONTRACT.md:3`). No tests were executed in this research lane; test names were inspected only.

| Existing value-level type | Preserved fields / validation | What it does not settle |
|---|---|---|
| `TextFactValue` (`:64`) | Exact supplied nonempty Unicode text, no silent trimming/truncation. | Meaning, approved field taxonomy or source ownership. |
| `NumericFactValue` (`:74`) | Point/range/lower/upper/unknown shape; exact/approximate/unknown; inclusive endpoints; currency **or** unit; scale-as-stated, period, period-reference, component, cadence and tax treatment. Decimal precision rejected rather than rounded. | Conversions, business taxonomy or whether an amount is budget/revenue/arrears. A scale token does not multiply the number. |
| `UnknownFactValue` (`:176`) | Explicit unknown with optional reason, distinct from an absent/unrecorded fact. | Whether a field was requested, withheld, inapplicable or erased; those need governed states. |
| `SourceSupport` (`:190`) | Support ID, source lifecycle ID, source revision ID/number, kind and raw wording. | No timestamp/span locator, owner/tenant, permission, current availability or validation that two support IDs are independent corroboration. |
| `FactRevision` (`:223`) | Fact/revision identity, field key, typed value, nonempty unique support IDs, superseded revision link. Frozen value structure. | No person/business/opportunity identity; no correction author, confirmation state, classification, effective time, relation or persistence API. |
| Successor validation (`:302`) | Same fact and field key, next consecutive revision, new revision ID and immediate predecessor link. | Database concurrency, erasure, merge/unmerge or reclassification policy. Moving a fact to a different field cannot silently change its stable field key in this chain. |

### Proposed subject and fact coverage for research reconciliation

These are semantic buckets for the next design fixture and updated-source review, **not approved storage fields or endpoint names**.

| Subject / view | Supplied information worth preserving | Boundary |
|---|---|---|
| Person | Stated name, role, work contact, decision participation, stated communication preference. | Separate the person from a business and a specific buying decision. No name-only automatic merge or inferred sensitive traits. |
| Business | Supplied business identity, industry/location, operations, team/processes, current tools, stated financial facts with periods. | Attribute each value to its source and subject. Do not assume a contact owns a business or that a monthly number is annual revenue. |
| Opportunity | Specific need, current situation, desired change, stated constraints, budget meaning, participants, evaluated offer, objections, explicit outcome/commitments. | A seller proposal is not buyer agreement; one business may have multiple unrelated opportunities. No automatic sales-stage advancement from silence. |
| Unclassified supplied detail | Exact wording plus source and candidate subject when not enough information exists to classify faithfully. | “Other supplied detail” prevents omission by fixed cards. It does not authorize indefinite retention, irrelevant personal collection or automatic extraction. Classification remains reviewable. |
| Conflict / correction | Both source-backed statements, timestamps/revisions, current review status, proposed correction and history. | No quiet last-write-wins. Distinguish a factual correction from a newer true value and from two simultaneously valid contexts. |
| Call membership | Explicit source/call/run association to the relevant subject and opportunity. | Same name, shared uploader or similar issue is not sufficient identity. Linking a call does not automatically share private learner coaching. |

Required design states: supplied fact, unknown, unrecorded, unclassified, disputed/conflicting, correction draft, append-only correction proposed/confirmed, newer source revision, source unavailable/revoked, unlink requested/confirmed, duplicate identity review, and independently supported versus solely source-derived. Proposed UI labels must not be presented as backend enum values.

Open protected decisions for updated sources: owner/tenant and sharing; which work contacts and business facts may be persisted; permitted sensitive incidental content; source-span representation; taxonomy and reclassification; subject linking/merge rights; source/call/account deletion consequences; independently corroborated facts after one source is removed; retention periods; audit metadata versus personal content; extraction/adjudication authority. No numerical retention period or erasure exception is invented here.

The owner's “no data point omitted” is carried forward as a fidelity and coverage requirement for supplied, relevant information. A future acceptance fixture should reconcile each supplied statement to a structured fact, an unclassified detail, a conflict/unknown or an explicitly excluded category with a reason. It must not claim completeness by counting cards, truncate lengthy facts, or transform all plausible inferences into stored facts.

## G10 · report advice versus private learner practice

Current `NextCallPlan` uses local active/opened state and reads report overview focus/practice/outcome (`app/next-call-plan.tsx:29`). It presents Keep/Change/Practise and source actions; no persistence call appears in that inspected component. `overview.practice.success_condition` is advice from one report, not canonical learner completion. This is not a repository-wide claim that no coaching storage exists elsewhere.

| Proposed concept to reconcile | Minimum distinction the UI needs | State / acceptance boundary |
|---|---|---|
| Source-backed suggestion | Call/run/transcript/report identity, original suggestion and selected evidence. | A new report revision may supersede the suggestion; preserve which revision the learner saw. |
| Learner selection | Learner-owned chosen focus, optional alternative/challenge/defer, original versus edited wording. | Selection is not saved. Private focus does not become buyer fact or shared report feedback. |
| Private reflection / note | Author, source association, unchanged original suggestion, edited text and revision. | Draft/pending/confirmed/accepted-but-unconfirmed/conflict must be distinct; retain local draft on failed confirmation. Actual persistence contract still needed. |
| Voluntary completion | Learner's own statement and its time/context. | No automatic mastery, certification, streak, sales outcome or provider call merely from saving/completing. |
| Multi-call comparison | Deliberately selected comparable call evidence and same learner role with uncertainty. | Calls with different prospects are not one prospect journey. No new numeric skill scale from UI convenience. |
| Removal / source change | Private note lifecycle and source availability relationship. | Deletion/retention and whether any source-independent note may remain require updated controlled decisions. No stale playable excerpt after revocation. |

Until persistence is defined, design fixtures should say “draft” or “example”, not show a production Saved success. The current report-derived focus can still be made clearer and more useful without enabling the proposed longitudinal domain.

## Next deliverables, without another arbitrary image quota

1. One reusable report adapter fixture table spanning valid legacy/projected/partial language and evidence states above.
2. One first-viewport composition using only verified duration, observed outcome and source evidence, with explicit unavailable metrics; retain all supported detailed points.
3. One Calls sequence proving loaded-query scope, approximate length, rename, pagination and return.
4. One route parity sequence for acquisition and legacy navigation using their actual existing components.
5. One fictional prospect fact-detail sequence with exact numeric/source fidelity, unclassified information and correction; no live writes until updated semantics settle.
6. One learner practice sequence separating suggestion, local draft and proposed durable save; no false longitudinal progress.

Research exit criteria: each displayed value has an exact source or explicit proposed status; each new semantic decision has an updated-source owner; each interaction has a failure/recovery/return condition; supported capability is distinguished from runtime verification. Static images can follow these contracts, but cannot establish any of those conditions by themselves.

## Verification receipt

Read-only source inspection and targeted text searches at the pinned revision; inspected working-copy status of the prospect module/test/evidence and mounted navigation. Some PowerShell wildcard-path searches failed with filename syntax errors; they were repeated with `rg -g` or exact paths. No product files modified, no browser, no build/test/provider run, no image generation or deployment. Only this research document is owned by this lane.

Fingerprint table is appended below after the final source read. These hashes establish inspected bytes, not test success or release acceptance.

| Inspected file | SHA-256 |
|---|---|
| `apps/sales-xray-web/app/report-contract.ts` | `240ef7c979170244c9a89ebd797d9f83f1e7b06f6d886409e0f6a66f8b61d822` |
| `apps/sales-xray-web/app/overview-contract.ts` | `d7ea95e8d4ca986fe517d35d8652afc52a09610ed893dbc1e78ee30c806c4537` |
| `apps/sales-xray-web/app/dipak-overview.tsx` | `92158b49d30cbe1bc10b00f2ca757f110627a42eda14938776ed7d7e46971bb3` |
| `apps/sales-xray-web/app/measurement-contract.ts` | `f4427ff678c7625e937cecb1402e4a732c7db67d40b17ff2b35fb75618f326c3` |
| `apps/sales-xray-web/app/recording-measurements.tsx` | `30950140a1f3eb0562e8ed39ff9728a05c5043c874705d45ceccc061dfc38bdd` |
| `apps/sales-xray-web/app/acquisition-client.ts` | `ec1ae2c3f84ac9f4cef832e2ad41703d1a02e1550fdc275346605440d1cd4bc7` |
| `apps/sales-xray-web/app/calls-library.tsx` | `c71a8050ca70f0751cd5ac19f6e19f72e764f42656cab612f82c3a5783055a77` |
| `apps/sales-xray-web/app/next-call-plan.tsx` | `36f5c919734213af5f72c7cea5165ecc63022174e1e578648ba31c7775e4ce13` |
| `apps/sales-xray-web/app/report-explorer.tsx` | `8243b2b641b316c9a6e526610251dfa4ced7569858fd298c21eaccdc13eba4b0` |
| `apps/sales-xray-web/app/report-navigation.ts` | `3c71e4385be07af3b555032c653ec4f93c30a332d4815a4fac27512b598eb414` |
| `apps/sales-xray-web/app/report-modes.tsx` | `6937cf73c7e9bb082a1bd5ecd897d5b6591a167da86d6a19ba27b19bd4a1aed7` |
| `apps/sales-xray-web/app/report-reading-context.tsx` | `a7590d950dc0258c449668391f29dce0760edb4d13a5dc34dd67ba77d08b9e94` |
| `apps/sales-xray-web/app/acquisition-studio.tsx` | `fb70df3c81b217e1d6326d8a7cdcc30d5fdaedfb96fc4a10e4f2dcc5d707fa48` |
| `apps/sales-xray-web/app/call-studio.tsx` | `1be640f7f87cd8b501f9afbe6f0dbe375d4b36790c713456b3d5538084ea6758` |
| `apps/sales-xray-web/app/report-header.tsx` | `1b1bd5dd3c0c15bb667641eebfa5638cb34a25112854c3e35a2628adca2f52a4` |
| `packages/python/ac_platform/conversation_intelligence/prospect_fact_contract.py` | `a541d9b288a98b6a230d131952df607aba985183c0c9528a1fe8d7f98e3adb1a` |
| `tests/unit/conversation_intelligence/test_prospect_fact_contract.py` | `06c404be4f1aaef8fd701d91afb4feb70168881805971efe258d794f9f3ba99c` |
| `docs/evidence/20260926_SALES_XRAY_PROSPECT_FACT_CONTRACT.md` | `0ae791af1ce5ed330a484c224f0edd7c2d2d0b7e09dd7c5cad1c1cc0ca37ab1f` |
| `docs/research/sales-xray-ui-completeness-20260927/RESEARCH-REPORT.md` | `e86d6474bce8b94b7e35df2faee0ab5a71c0927a06975d8466b1f30163c7092c` |
| `docs/research/sales-xray-ui-completeness-20260927/LOCAL-SOURCE-AUDIT.md` | `bb2e44b69845bbfe02449f86e65e829c2cc094989f48614e8adb57091fb2c22a` |
| `docs/design/sales-xray-v02-refresh-20260926/DEVELOPMENT-PLAN.md` | `56090f78fcf3db08f58f86118c49ae961aa182854d6a997297e65ebce51bc32e` |
| `docs/design/sales-xray-v02-refresh-20260926/INTERACTION-CONTRACTS.md` | `263fead800a54df23c7b16e64101dde46b1d2473e0a0c37c9ff6657d920cc72e` |
