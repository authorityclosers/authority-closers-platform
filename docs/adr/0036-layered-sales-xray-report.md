# ADR 0036: Layered Sales Xray report

Date: 2026-09-29. Status: Accepted — owner approved the AUT-72 plan rev 3 on 29 Sep 2026.

## Context

The current report pipeline has three AI stages: C2 transcript, C4 facts per chunk, and C5 judge. `processing_plan.py:241` requires exactly `("C2", "C4", "C5")`; stage codes are `VARCHAR(2)` with database checks. Each stage uses a governed provider route. The approval pins the recipe (`processing_plan.py:262-263`) and report profile hash (`:266`, `authority.py:941`); a new AI stage or a swapped profile requires new approvals in every environment.

Prompt versions are selected per environment in analysis settings. The existing C5 coaching prompt revisions are `coaching-v3` through `coaching-v6` (`analysis_settings.py:31`, its DB check, and migration 0049 are the pattern for adding a revision). Packs are pinned by SHA per revision (`qualitative_pack.py:110-125`).

C5 currently fills eight fixed skills from `profiles/dipak_report_v1.json`. A `not_applicable` status already exists (`reports.py:269-275`). C4 returns a free-text overview and `observations[{statement, evidence[{segment_id, quote, start_ms, end_ms}]}]`, but people, budget, dates, tools, and next steps are not structured. Talk/listen ratio, questions, monologue, and interruptions are not computed. Re-running only C5 is supported: a new plan reuses finished C2 and C4 tasks by `cache_key` (`processing_plan.py:1061-1082`).

## Decision

The report has four separate layers. Each layer has its own output block and version. Later layers do not change earlier ones.

| Layer          | Output                                                                                         | Made by                                                                                                                                                        | Runs                                   |
| -------------- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| L1 Call Record | Facts only: numbers, facts with quote and time, people, business data, commitments, next steps | Numbers: code from C2 segments (no AI). Facts: C4 observations. Categories: `fact_tags` block in C5 v7                                                         | Automatic                              |
| L2 Call type   | One of nine types, confidence, one-line reason, timeline phases                                | `call_type` block in C5 v7                                                                                                                                     | Automatic                              |
| L3 Analysis    | Only the skills in that type's rubric; skipped skills are `not_applicable`                     | C5 v7 with the type's rubric                                                                                                                                   | Automatic; none for `not_a_sales_call` |
| L4 Coaching    | Keep doing / Change first / Next call, each with an Academy link slot                          | v1: existing C5 coaching fields, shown only in the Coaching tab behind “Coach me on this call”. v2 (only if the cost check says so): a separate on-request run | On request                             |

### Recorded decisions

- **D1 — Four layers:** Use a separate output block and version for each layer. Later layers do not change earlier ones. L1 contains facts, L2 the call type, L3 type-specific analysis, and L4 coaching on request.
- **D2 — Call type in C5:** The call-type step is part of a new C5 prompt revision, `coaching-v7`, rather than a new stage. C5 already reads the transcript and C4 facts and needs the type to choose a rubric. One request produces `fact_tags`, then `call_type`, then analysis. This requires no new provider route, approval kind, stage code, or extra request, so it adds no spend path. Select v7 per environment in analysis settings: dev runs it first; staging gets it only after the golden set passes. If the golden set shows poor type accuracy, classification may move to its own request later as a governed provider change through the CEO.
- **D3 — Call types v1:** Use the owner-approved list in `profiles/call_types_v1.json`: `discovery`, `demo`, `closing`, `follow_up`, `buyer_briefing` (listening call), `negotiation`, `account_check_in`, `not_a_sales_call`, and `other`. Definitions and detection signals come from the Call Quality Lead's draft (AUT-130). If confidence is below 0.6, ask “What kind of call was this?”.
- **D4 — Hard validation guard:** Code must reject any v7 output that fills a skill on the type's skip list, and any analysis or coaching for `not_a_sales_call`. Owner-approved v1 skip lists are: `buyer_briefing` skips `closing_decision_management` and `solution_relevance_presentation` (no closing or pitch critique); `not_a_sales_call` skips all eight skills. Other skip lists come only from Dipak's signed-off rubrics. A rejected output is a validation failure (repair or fail), never shown.
- **D5 — Protected rubric content:** Engineers build the mechanism. Rubric files ship only from the rubric draft Dipak signed off (AUT-130 → CEO → AUT-127). Nobody writes rubric content in a PR. Keep the base profile `dipak_report_v1.json` and its approval hash unchanged; per-type rubrics are packs pinned by SHA under v7. Numeric scoring stays off until the AC-SVAL gates.
- **D6 — Change call type:** When a user changes the type, only C5 reruns. A new plan carries an optional `call_type_override`; C2 and C4 are reused by `cache_key`. Keep the old type and supersede it with actor and time; never overwrite it. Quote and budget-check the rerun like any AI run.
- **D7 — Versioning:** Record `taxonomy_version`, `rubric_version` (SHA), `prompt_revision`, and `copy_version` on every v7 output. The Report Lab CLI compares two revisions on the same inputs.
- **D8 — Golden sets:** Real content never goes in Git. CI uses fictional text fixtures, one per call type, including a fictional listening call. Fixtures are package data with recorded outputs, so CI makes no AI calls. The real golden set (5–8 internal testers who agreed, picked by Dipak, including the tester's listening call) stays on the dev host in a read-only directory with C2 and C4 JSON only. Git holds only a manifest with id, expected type, and why the call is in the set. No transcript text, names, or audio goes in Git. Do not use customer calls until the consent wording is approved.
- **D9 — Automatic checks:** Use plain code, with no AI and no new dependency, for reading grade 6–8 (Flesch–Kincaid with our own syllable counter), at most 20 words per sentence, a versioned banned-jargon list with plain replacements, a quote and time for every claim, call type matching the manifest's expected type, no analysis or coaching for `not_a_sales_call`, and no skip-listed skill for any type. Run checks in CI on the fictional set and on dev on the golden set. The scorecard shows tokens and cost per call.
- **D10 — Coaching cost rule:** L1–L3 run automatically. The Coaching tab is on request. RL8 measures the coaching share of C5 output on the golden set and the cost of a separate on-request run. The CEO/owner then fixes the rule. Build L4 v2 only if on-request generation saves money.
- **D11 — API shape:** Give the Call Record (numbers, facts, tags, and call type) its own endpoint, `GET /v1/conversation/submissions/{id}/call-record`, so the strict web parsers (`report-contract.ts`, `overview-contract.ts`) and stored report hashes (`report_store.py`) do not break. New report-draft fields default to excluded.
- **D12 — No sentiment line in v1 (CEO, 29 Sep 2026):** Buyer concerns show only in the buyer's own words, with quote and time (`concern` fact tag). The current C5 rule stays: words only, with no emotion, tone or trait claims. A mood line from text, or emotion from audio, stays out of scope until after Reviewer Studio v2.

## Alternatives

- A separate call-type request was not selected for v1. D2 places classification in the C5 `coaching-v7` request; a separate request is a later option only if the golden set shows poor type accuracy, and it requires a governed provider change through the CEO.
- Automatic coaching was not selected. D1 and D10 keep the Coaching tab on request; a separate L4 v2 run depends on the RL8 cost check.

## Consequences

The report separates facts, call type, type-specific analysis, and coaching. L1–L3 are automatic, while L4 is requested by the user. Hard validation keeps skipped skills and `not_a_sales_call` output out of reports. Call-type overrides preserve prior history and reuse completed C2 and C4 work. Output versions and the dedicated Call Record endpoint let the CLI compare revisions without changing the strict report parsers or stored report hashes.

The v7 prompt is enabled per environment through analysis settings. Dev runs first; staging waits for the golden set to pass. Fictional fixtures keep CI independent of AI calls, while the real internal-tester set remains read-only on dev. Customer calls remain out until consent wording is approved.

## Data and safety

- Use only internal testers who agreed, with read-only access ([AUT-129](/AUT/issues/AUT-129)). Do not use customer calls until the consent wording is approved.
- Do not put secrets in fixtures, prompts, logs, or pull requests. Fictional names only go in Git.
- Overrides and coaching requests are append-only. Supersede history; never overwrite it.
- Dev AI runs stay under the dev AI cap. Enable v7 in staging only through analysis settings after the golden set passes and via the normal release path.

## Reversal cost

Changing the layer outputs, call-type taxonomy, rubrics, or API shape requires coordinated updates to their consumers and stored output versions. A new AI stage or changed profile also needs new provider-route approvals in every environment. Any change to override history must preserve append-only supersession.

## Evidence

- [AUT-127 architecture document](/AUT/issues/AUT-127#document-architecture), revision 3, sections 1, 2 (D1–D12), and 5. It records the owner-approved AUT-72 plan revision 3 dated 29 Sep 2026.
- Current pipeline details and implementation references are recorded in section 1 of that architecture document.

## Owner

Accepted under the owner-approved AUT-72 plan revision 3 on 29 Sep 2026.

## Supersedes

None.

## Trigger to revisit

Revisit if the golden set shows poor type accuracy; if RL8 shows that a separate on-request coaching run saves money; if the owner-approved call-type list or signed-off rubrics change; when the AC-SVAL gates change the numeric-scoring boundary; or when Reviewer Studio v2 reopens mood or emotion.
