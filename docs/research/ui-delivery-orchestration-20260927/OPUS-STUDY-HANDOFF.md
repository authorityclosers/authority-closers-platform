# Opus study handoff: Sales Xray UI delivery

Prepared 27 September 2026 for the owner's request to have Opus understand and independently assess the complete design-delivery approach. This task is study, critique and an executable handoff; it does not launch implementation or deployment.

## Your assignment

Act as a senior product designer and frontend engineering reviewer. Study the actual selected designs, the current app structure and the research below. Form your own judgment. Do not simply agree with Codex, rewrite the research in different words, or produce generic advice about making an app “Apple-like.” Explain exactly how you would reproduce this particular visual direction with reliable behavior, one screen family at a time.

The owner already likes the images delivered to Drive and dislikes the newer locally generated alternatives. The problem is translating the chosen designs into a polished working app without losing their proportions, hierarchy or interactions. The previous attempt to handle the entire library together did not meet that standard. We need a disciplined delivery method, not more agents or more images as a proxy for progress.

Your output must show what you inspected, what you understand, where the research is wrong or incomplete, which modes you recommend, and a fully specified first screen packet for the implementation writer. Continue independent study where information is missing; ask only about a product decision that cannot be resolved from the current owner direction and available evidence.

## Environment and ownership

Main repository and research output:

`D:/Projects/authority-closers-platform`

Existing source/design checkout to inspect read-only:

`C:/Users/Suyash/.codex/worktrees/sales-xray-v02-core-release-20260925/authority-closers-platform`

Its last research snapshot was `e488f952b1aafc10761f304630965d8233a2e39b`, with uncommitted changes. That is a historical observation, not an instruction to reset or a claim about today's HEAD. Record the actual branch, HEAD and relevant dirty files before judging implementation status. Preserve concurrent work. Do not create a new checkout or install dependencies for this study.

Read applicable repository/ancestor `AGENTS.md` and any `CLAUDE.md` instructions. Read:

- `C:/Users/Suyash/.codex/skills/ac-orchestra/SKILL.md`
- `C:/Users/Suyash/.codex/skills/workflow-ui-production/SKILL.md`

Apply AC Orchestra for bounded research and evidence-based handoffs. Use the existing research chat if an unresolved question needs cloud work; verify that the necessary tool/account is actually available before promising it. Do not start a recursive Codex → Claude → Codex agent chain. Codex remains the coordinator/integrator; a future screen has one implementation writer and a fresh read-only reviewer.

The Windows PC has about 7.36 GiB usable RAM. Before any heavy browser export, installation, build, test suite or dev stack, run `python C:/Users/Suyash/.codex/tools/pc-health/health_check.py`. An exit code of 2 means use a lighter workflow or resolve the shortage first. One heavy local job at a time. Source and document reading do not need a new build.

## Reading order

Let RESEARCH mean:

`D:/Projects/authority-closers-platform/docs/research/ui-delivery-orchestration-20260927`

Read these files completely, including their limitations:

1. `ASTRA-OPUS-MODES.md` — latest mode policy and calibration proposal.
2. `MODE-REVIEW.md` and `MODE-SOURCES.json` — independent review, primary sources and disagreements with the cloud recommendation.
3. `README.md` — overall delivery workflow. Its older model table is superseded for the initial quality-calibration screen by the mode addendum.
4. `SCREEN-PACKET-TEMPLATE.md` and `PILOT.md` — the bounded work unit and proposed comparisons.
5. `RESEARCH-REVIEW.md`, `INPUTS.json`, `SOURCES.json` and `MANIFEST.json` — dispositions, inspected bytes and evidence trail. Use INPUTS to locate relevant implementation files, not as proof those files are unchanged today.

Existing completed Pro research conversation:

https://chatgpt.com/c/6ab8b0ab-0a80-83e9-857e-b9c4cf77f425

The local documents are sufficient to begin. Do not block the study solely on chat access. Research responses are suggestions to evaluate, not authority to change product semantics or permissions.

## Selected designs and precedence

Let DESIGN mean this directory inside the existing source checkout:

`docs/design/sales-xray-v02-refresh-20260926`

Read in this order:

1. `OWNER-VISUAL-DIRECTION-20260927.md` — current owner selection.
2. `README-START-HERE.md`, `DEVELOPMENT-PLAN.md`, `INTERACTION-CONTRACTS.md` and `VISUAL-REVIEW.md` — interpret through the newer owner selection.
3. `DELIVERY-STATUS-20260926.md` — historical delivery receipt, not current feature completion.
4. `state-manifest.json` and `index.html` — map workflow families and inspect actual image references in manageable groups.

Company Drive library:

https://drive.google.com/drive/u/0/folders/1akhxdM1yTs_IHwUneJ6HOjEcBP_HDhxF

The saved receipt records 204 delivered images: 192 original states, 10 corrections and 2 earlier concepts. That does not mean 204 individually approved implementations. The selected overall visual direction coexists with factual and interaction corrections. Resolve those corrections without replacing the style.

Do not use `expansion-images/` as the visual direction. Do not restart the older 240-image expansion merely because its plan still exists. New filenames or changed mock data do not prove a missing workflow. Do not execute `C:/Users/Suyash/.codex/private-artifacts/ui-reference-refresh-20260926/OPUS-TASK.md`: it is explicitly superseded and contains historical instructions around only two early concepts.

Open the actual report overview desktop/mobile images first:

- `images/06-report/06-report-01-overview-desktop.png`
- `images/06-report/06-report-01-overview-mobile.png`

Then inspect representative selected states for shell/navigation, upload, processing/recovery, calls, prospects, account/settings, providers and admin. Use the manifest to find exact paths. Report which images you actually viewed. Do not claim every image was inspected if only a sample was opened. Preserve a coverage checklist for deeper per-screen study. Raster image dimensions are not automatically CSS viewport dimensions.

The owner's recent direction takes precedence over stale visual plans. The old BRD must not decide the new UI. Existing security, tenancy, consent, billing and data contracts still require evidence; distinguish those from visual authority. Follow the repository's controlled-document fetch requirements before any future implementation, using exact source IDs rather than filename guesses. An unresolved protected capability does not block unrelated UI study.

## Owner requirements that must survive the handoff

Treat these as a requirements map to reconcile with current source and selected references. They are not claims that the backend already supports them.

- **Shell and layout:** standalone Sales Xray, with the Learner app's useful navigation behavior as a reference. Stable sidebar logo and collapse control; no vertical jump. Useful laptop viewport, fewer redundant headers, consistent spacing and clear mobile navigation.
- **Report hierarchy:** compact header, meaningful first viewport, clear takeaway and visually distinct keep-doing/change-first/outcome/next-call sections. Secondary export/deletion actions belong in an appropriate overflow menu. Keep access to provenance without showing raw revision hashes or unexplained Doc-3/section identifiers as primary content.
- **Report navigation:** clear horizontal tabs in tabbed mode, useful reading navigation, understandable transitions, preserved return position and keyboard focus. Motion must support orientation and respect reduced motion.
- **Evidence and audio:** contextual play and pause everywhere, one coordinated global player, useful clips, understandable minute/second timestamps, clear evidence links and no controls hidden behind a player or mobile navigation.
- **Visual analysis:** informative, interactive representations of real supported call evidence and measurements. Distinguish measured metrics, qualitative observations and unsupported scores. Do not invent win probability, emotion, skill numbers or radar charts to imitate a mockup.
- **Language and coaching:** readable English/Marathi/Hindi where selected, sensible wrapping, concise understandable coaching and meaningful citations. Brain document IDs alone do not explain advice. A polished UI cannot establish coaching accuracy.
- **Upload to report:** one deliberate start action, honest progress, preserved recording, smooth recovery and no unnecessary plan-review/restart loop. Recovery must respect idempotency, approval and paid-call history. Upload and completed reports must appear correctly in Calls.
- **Calls:** live supported data, useful duration/status presentation, easy naming, efficient search/list interaction, no duplicate headings or wasteful nested scrolling. Opening a finished call should not pretend to restart processing.
- **Prospects:** a distinct useful contact/business/opportunity experience, linked calls and detailed supported facts with provenance and corrections. Track requested depth against actual extraction/storage contracts; do not infer missing sensitive data or retention rules.
- **Account and access:** coherent profile and settings, useful allowance visibility, understandable access requests, and authorized admin minute/token grants with audit history. Do not present nonfunctional menu items as finished capabilities.
- **Providers/admin:** understandable configuration for transcription, analysis and writing; truthful connection/test states and secret handling. The owner prioritizes OpenAI in both analysis and writing. Do not claim it is active based on UI labels or this design research.
- **End-to-end quality:** loading, empty, partial, error, reconnect, keyboard, focus, long text, responsive reflow and reduced-motion states belong to each screen family. Screens must also work together across navigation.

Brain 3.x effectiveness, AudioAtlas use, provider benchmarks, allowance fixes and staging/production parity remain separate evidence-backed engineering workstreams. Identify dependencies without claiming they are solved. JEV research, Paperclip/VPS setup, WhatsApp/Telegram integrations and bulk generation are not prerequisites for this UI study.

## Independently assess the mode policy

The local proposal is Astra 6 xhigh for a precise screen contract and fresh review, with Opus 5.5 xhigh as the sole writer of the first demanding report/player family. The Pro follow-up favors high as the general baseline and xhigh trials on dense screens. Neither is a task-matched benchmark result.

Challenge that allocation. Explain when high is sufficient, when xhigh could matter, and what specific failure warrants max. Keep effort comparisons separate from writer-model changes and automatic delegation. Do not assume Opus is better than Astra at implementing these references. Propose the smallest fair comparison that can improve this decision, including repair/review overhead and unknown subscription usage.

For this study, verify the effective model and effort. The requested target is `claude-opus-5-5` at xhigh. Do not claim you changed settings through prose. Plan mode is a separate workflow/permission choice. Keep Ultracode and Fast off. Use only included subscription capacity, without API fallback or paid extra usage; stop at a service cap and save a concise continuation. This handoff does not assert that capacity has reset.

## Required deliverable

Write one self-contained study response with these sections:

1. **What I inspected and understood:** exact documents, source revision and images; demonstrated access versus missing inputs.
2. **My independent critique:** accept/change/reject each important workflow and mode recommendation, with reasons and primary sources for material current claims. Surface contradictions instead of silently selecting a convenient instruction.
3. **Workflow coverage:** selected references and known gaps by user task/state; distinguish visual correction, missing design, missing implementation and backend dependency. No image-count completion claims.
4. **First screen packet:** a report-overview candidate with the minimum required shell/player scope, exact references, allowed files proposed from current code, real data contracts, responsive widths, interactions, microstates, motion/focus, meaningful tests and visual acceptance criteria. If a different first slice is necessary, justify it with inspected evidence.
5. **Collaboration protocol:** one writer, fresh read-only review, explicit ownership, concise artifacts and escalation. Specify what Opus sends Codex and what Codex independently verifies before integration. No owner approval required for every routine spacing decision.
6. **Mode comparison and resource plan:** fixed inputs, effort settings, tools, stopping rules, repair limits and accounting. Mark experiments unrun.
7. **Next execution handoff:** ordered bounded tasks, dependencies and an exact first writer prompt, ready for the coordinator to dispatch after this study is reviewed.

If local document writing is available, save only this new file in the research directory:

`D:/Projects/authority-closers-platform/docs/research/ui-delivery-orchestration-20260927/OPUS-INDEPENDENT-STUDY.md`

If it already exists, preserve it and use a new timestamped filename. Otherwise return the complete response inline. Do not overwrite the research, source files or image library. This study does not authorize app edits, new images, installs, paid benchmarks, production changes or communications to customers. Mark any proposed test or deployment as unverified until real evidence exists.

Finish with your own concrete recommendation and the first actionable packet, not an offer to study later.
