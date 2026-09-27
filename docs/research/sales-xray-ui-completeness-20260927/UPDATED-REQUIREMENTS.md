# Sales Xray — updated business requirements baseline

Date: 27 September 2026. Status: current owner direction consolidated; proposed implementation choices and unresolved business decisions identified separately. This is a Sales Xray requirements update, not an approved replacement for every Authority Closers platform contract.

## Authority correction

The owner's latest instruction is explicit: **“old brd does not count we need updayed one so dont take decisons on that basis.”** The 29 August v0.5 BRD is historical and excluded from decision authority for this work. Its defaults must not be copied into new requirements, nor reintroduced indirectly through an old implementation plan. The old Master Index can locate documents; it does not make their contents current.

A focused company Drive search for `BRD` on this date showed August BRDs and elicitation sheets. It did not establish a newer current BRD. This is a bounded search result, not proof that a newer document does not exist. The connected Drive plugin was under another account; the successful search and exact-document reads used the Authority Closers browser account instead. Private receipts remain outside Git.

Authority order for this handoff:

1. Latest explicit owner directions and the supplied current AGENTS safeguards.
2. Exact newer source documents after their scope, revision and decision status are verified. The September intake records Brain 3.0, context, report, prospect and UX sources; its captured text and approval labels are evidence of that intake, not fresh adoption of every rule.
3. Current code as evidence of existing behaviour. It does not approve future business policy or prove deployed behaviour.
4. Research and mockups as proposals. Neither cloud output nor a large image library can promote itself into policy.

Owner-directed requirements below can guide design now. An unresolved decision blocks only actions depending on it; it does not stop shell, spacing, navigation, accessibility or faithful presentation work.

## Business outcome

A person should upload a call, intentionally start analysis once, understand its status, and receive a useful, plain-language, evidence-linked report in both the report workspace and Calls. The desktop and mobile applications should feel coherent and responsive. Operators should configure supported providers, understand what is actually active, manage access and diagnose problems without unsafe retries or opaque technical screens.

Success means a verified end-to-end journey and understandable sales feedback, not an image count, number of sections or model name. Staging and production each require their own release evidence before either is called complete.

## Owner requirements and acceptance evidence

| ID | Current requirement | Acceptance evidence required | Current research boundary |
| --- | --- | --- | --- |
| U01 | Standalone Sales Xray with the quality and interaction consistency of the learner shell | Expanded/collapsed/hover/focus states keep the logo and toggle stable; one host shell and one player; active route clear; usable laptop/mobile/zoom | Reuse suitable learner conventions; do not nest two shells or assume identical authentication |
| U02 | Use the viewport efficiently with polished typography, alignment and micro-interactions | Report content visible in the first normal laptop viewport; compact contextual header; no repeated Calls headings or excessive empty regions; motion respects reduced-motion preferences | Exact pixel geometry is a design choice, not inherited BRD policy |
| U03 | One intentional upload-and-analyse action | Valid file and required prerequisites lead to durable upload and admitted analysis without an unnecessary review-plan/continue loop; interrupted responses reconcile the same intent; Calls contains the same durable item | One user action may orchestrate several backend steps; upload consent and analysis admission remain distinct |
| U04 | Honest, smooth processing and recovery | Selected/uploading/saved/admitted/running/complete/failed states use canonical status; re-entry and refresh recover; do not restart paid work because polling failed | Clarify which state is safe to leave; local byte transfer does not survive full reload today |
| U05 | Real Calls and dashboard data | Names editable, duration provenance visible, filters/search scope stated, pagination and stale data handled; opening a complete call does not misrepresent it as new processing | Current duration is estimated and filters cover loaded rows; whole-library search requires its own service contract |
| U06 | Clear, useful report with Dipak's current source material | Versioned report-to-presentation map, understandable language, specific observed strengths/change/outcome/next step and source support; reviewer feedback against actual output | Brain label alone cannot establish use, coverage or quality; compare exact applied source and model receipts |
| U07 | Readable multilingual reports | English, Hindi/English and Marathi/English cases tested; selected language clearly presented; original quotes preserved; no default leakage or clipped scripts | Current language intake is recorded; new defaults must be deliberate, not copied from August |
| U08 | Rich visual overview | Each chart has a named source, definition, unit, time base, missing-data treatment and evidence drill-down; equivalent table/text access | No fabricated skill scores, emotional claims, win probability or speaker identity from physical audio channels |
| U09 | Evidence feels like a working application | Every supported clip can play, pause, resume and return; global and inline controls agree; excerpt bounds intentional; keyboard and mobile safe | Source revision and excerpt identity survive navigation; no zero-length or invented clips |
| U10 | Reading and tabbed navigation are coherent | Section arrival visible, Return restores origin and focus, browser Back/Forward predictable, horizontal tabs fit or scroll accessibly | Current acquisition already implements ReportModes return/arrival; verify parity with legacy routes rather than replace blindly |
| U11 | Hide irrelevant technical artifacts without hiding truth | Hashes/revision diagnostics and export/deletion move to appropriate details/overflow; document references use understandable source names; unverified status remains discoverable | Raw `Doc-3 §…` is not recording evidence. Never relabel a proposal as adjudicated |
| U12 | Complete prospect information, with a separate destination and profile | Capture every supplied business-relevant fact with provenance, exact values/ranges, conflicts and an unclassified-fact path; contacts, businesses and opportunities remain distinguishable | Existing fact primitives are not a CRM. Ownership, linking, persistence and deletion decisions D03–D05 remain explicit |
| U13 | Useful next-call plan and practice | Clear suggested words, source moment, selected focus and optional practice; any saved note/bookmark/completion has real persistence and conflict recovery | Current report advice/local selection must not pretend to be saved coaching history |
| U14 | Account and profile are real features | Name/contact/avatar capabilities have clear ownership, save/conflict/unknown-result behaviour; preferences show where they persist; sign-out usable | Do not imply shared learner-avatar synchronization without its confirmed contract |
| U15 | OpenAI for analysis and writing, with provider flexibility | Separate stage selections and exact run receipts for analysis and writing; supported schemas validated; quality, clips, latency and cost compared on authorized fixtures | UI selection is not evidence of execution; one writing-only run cannot prove analysis coverage |
| U16 | Extensible provider configuration, including user-supplied keys | Discoverable supported provider/model capabilities; secure credential intake, masked reference, connection lifecycle and scoped use; unsupported entries labelled | “Any provider” is an extensibility goal, not a claim every API supports every stage. BYOK isolation/billing/egress decisions D06 required |
| U17 | Better transcription choices and AudioAtlas clarity | Compare supported transcription engines on relevant authorized languages/audio; show which transcript and measurements feed analysis/writing, with timestamp quality evidence | AudioAtlas physical measurement is distinct from speech transcription and sales interpretation |
| U18 | Admin can grant access and users can request more | Audited account-specific grants, usage, request status, same-operation recovery and confirmed notification status; no confusing token/minute labels | D01 separates minutes, tokens, cost and unlimited testing; existing finite grants are not the complete requested capability |
| U19 | Operations settings are understandable and testable | Configuration saved, tested, approved and active states distinguished; prior plans retain exact route; failures and current revision recover visibly | Hosted benchmark controls are currently absent in inspected UI; local runner is not an Admin endpoint |
| U20 | Export and data controls stay available without dominating report UI | Discoverable overflow, accessible confirmation, precise export format/state and deletion lifecycle; report remains usable on export failure | Current direct DOCX download and deletion acceptance do not prove async export/cascade completion |
| U21 | Reviewer feedback can improve quality | Exact assignment/source/run, independent reviewer identity, draft preservation, expiry/revocation and saved proposal receipt; adjudication distinct | Dedicated Admin `/reviewer/*` is active; retired learner reviewer pages are not the implementation target |
| U22 | Consolidated, tested releases on staging and production | Trace source revision, tests, actual UI journey and runtime revision in each environment; preserve audit evidence and rollback | No deployments in this research batch; mockups do not establish release readiness |
| U23 | Exhaustive connected design coverage, not two hero images | Workflow, alternate states, errors, recovery, empty data, permissions, desktop/mobile and micro-interactions mapped to evidence and designs | 204 references and 240 planned slots are inventory, not completeness or acceptance |
| U24 | Respect resource and delegation constraints | Reuse AC Orchestra research; no Opus while paused or paid overflow; one heavy local task at a time; preserve active work | Current task is research, so no build/provider/image-generation/deployment job is started |
| U25 | Preserve next-version research commitments | JEV economics/development assistance, broader provider/transcription research, VPS/Paperclip and messaging requests remain separately tracked | They are not silently dropped, nor treated as prerequisites for the present UI contract work; no claim near-zero cost or automatic quality improvement |

## Decisions requiring updated semantics

These are explicit gaps, not decisions delegated back to the old BRD. Research can recommend options, but the table must not present an inference as an approved rule.

The owner sets business policy; the implementation owner supplies feasibility and exact code/service evidence; a source/review owner verifies adoption and quality claims. This handoff assigns no approval powers to an AI model. Every resolved decision should append its dated rationale, owner/source, superseded assumption, affected requirements and tests. Do not rewrite historical approval records.

| ID | Decision to settle | Needed precision and affected capability | Safe research/design treatment now |
| --- | --- | --- | --- |
| D01 | Allowance units and administration | Are “tokens” an internal entitlement unit, provider tokens or a spend budget? Define minutes measurement/rounding, reservation/settlement, expiry, reversals, grant scope, and unlimited-testing exceptions | Model separate typed ledgers; no conversion formula or unlimited production cost implication |
| D02 | Retry cost and new-run permission | Provider-specific charging evidence for rejection, 5xx, timeout and completed-but-lost response; attempt limits, retry token ceilings, user allowance treatment | Reconcile existing intent first; unknown spend remains unknown; do not label every 5xx free |
| D03 | Prospect entities and ownership | Person/contact/business/opportunity identifiers; tenant/owner relationships; access roles; explicit versus suggested call association | Design separate entities with source-linked facts; no automatic identity merge or cross-account sharing |
| D04 | Prospect lifecycle and retention | Call unlink/delete, account deletion, source revocation, independent corroboration, audit/legal needs and erasure status for each derived record | No indefinite retention default; depict requested/in-progress/complete/partial states pending chosen policy |
| D05 | Prospect detail categories | Exhaustive supplied business facts, unclassified facts, extraction review, conflicting values, sensitive-field treatment, correction/reclassification semantics | Preserve supported original facts; no external enrichment or invented sensitive traits |
| D06 | BYOK and provider gateway | Credential owner, vault path/reference, egress destinations, model capability validation, who pays, revocation/rotation, supported endpoints and request caps | Masked placeholders only; catalog presence is not activation; no browser storage of secrets |
| D07 | Profile and preferences authority | Shared learner versus standalone fields/avatar; cross-app propagation; local versus account-level preferences and draft handling after session expiry | Label locality and supported fields; no silent synchronization claim |
| D08 | Access requests and notifications | Request lifecycle, authorized resolver, decision reasons, notification channels/opt-in, delivery receipt and retry semantics | Keep request, grant and notification identities separate; balance change does not prove delivery |
| D09 | Brain/source adoption and adjudication | Exact adopted September documents/sections, prompt/report schema, rule conflicts, reviewer and final authority, source freshness, language quality acceptance | Record applied revisions; distinguish source citations, observations, corrections and approved conclusions |
| D10 | Practice and longitudinal learning | Author, scope, saved selections, voluntary completion, deletion, comparability across calls and permissible progress claims | Section 13 has no supported progress now; no invented longitudinal improvement score |
| D11 | Upload eligibility and concurrency | Guest/anonymous boundaries, profile prerequisites, consent snapshot, simultaneous upload limits and back-pressure | State existing behaviour; do not derive production eligibility or capacity from a mockup |
| D12 | Search, measurements and export contracts | Whole-library query/index/count scope; measured versus estimated duration; transcript definitions for questions/turns; export formats and source-version binding | Show exact supported capability and unknown coverage; propose new services explicitly |

Follow-through detail from Pro's challenge: D02/D11 also need cancellation and abandoned-upload retention; D07/D09 must distinguish changing display/report language from a newly paid translation/regeneration; D06 needs explicit fallback behavior; D12 needs DOCX source-snapshot and access semantics. Existing settings/navigation must not silently perform these actions. Per-route history/dialog-close behavior is a testable engineering contract unless it changes access or product semantics.

## Delivery slices

1. **Faithful application experience:** shell, compact report header, existing evidence controls, reading return, coherent Calls and account routes; preserve current durable-operation identities. Use exact current data with clear missing states.
2. **Data and workflow depth:** complete fourteen-point adapter/fallback treatment, source-aware graphs, meaningful settings capability states, source-linked prospect review and practice contracts. Implement persistent features only after their affected decisions are resolved.
3. **Provider/access operations:** secure provider extensibility, real benchmark lifecycle, stage-specific OpenAI verification, grants/requests/notifications. Each capability needs its own verified endpoint and persistence proof.
4. **Release proof:** connected keyboard/pointer/mobile sequences, reload/session/late-response fault cases, source/version integrity, and staging plus production receipts. A slice can ship independently once its own requirements pass.

See [journeys](JOURNEY-CONTRACTS.md), [evidence/data](EVIDENCE-DATA-CONTRACTS.md), [operations/settings](OPERATIONS-SETTINGS-CONTRACTS.md) and [next design queue](NEXT-DESIGN-QUEUE.md). This document does not claim application changes or new approvals occurred.
