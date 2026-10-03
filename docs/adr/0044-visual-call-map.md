# ADR 0044: Visual Overview call map (`call-map/1`)

Date: 2026-10-03. Status: Accepted (architecture) — CTO plan on [AUT-341](/AUT/issues/AUT-341), rev 1 with the AUT-416 amendment and the 30 Sep decision brief (revision `a25dd6ea-4577-43a7-a2b7-c37e83437100`).

## Context

The owner judged four Sales Xray reports against their transcripts and found nine defects that repeat in every call: provider speaker labels in prose, dimension states that do not discriminate, an unchecked time promise, budget never flagged, seller errors called vocabulary, unverifiable promises missing from ethics notes, no record of who raised a pain, an undetected engagement collapse, and invisible cross-call patterns. The fix is a visual Overview drawn from structured fields: timing measurements the system computes, and a small AI block of readings backed by quotes. This ADR records the contract decisions. It activates no prompt and approves no scoring.

## Decision

- **D1 — Two sources, one screen.** The web computes the timing visuals from the transcript segments it already has (`call-metrics.ts`); a Python twin passes the same test vectors. No AI, no back-end change for the visuals.
- **D2 — The AI fields ride inside C5 as prompt revision `coaching-v7`**: v6 plus a `call_map` output block and the honest-report rules. Same pack, same provider routes, no new stage or spend path. Report Lab's typed prompt becomes `coaching-v8` and reuses `call_map.phases` and `call_map.money` instead of adding its own.
- **D3 — v7 is a candidate.** It stays fail-closed at runtime until AC-SVAL-01 Gate 2 evidence and the owner's approval are recorded. Amendment 2 of the plan lets AC's own workspace preview the candidate, labelled, under `sales_xray.candidate_preview`.
- **D4 — Storage.** `call_map` is an optional report-draft field, left out when unset, so stored v4–v6 report hashes do not change (ADR 0036 D11).
- **D5 — Serving.** A separate read endpoint next to the report, so the strict web parsers never meet an unknown key.
- **D6 — Roles.** `call_map.speakers` is the AI's reading of seller and prospect. Trust order: the speaker map (ADR 0042), then `call_map.speakers`, then none.
- **D7 — Additions to the owner's table:** `speakers[]`, ids on pitch items, pains and claims, `qualification_confirmed[]` (a gap is the default; confirmation needs a quote), `claims[].seller_error`, `prospect_tasks[]`, and evidence on every item. `next_step_rung` lives only inside `outcome`.
- **D8 — Honest dimension states.** v7 adds `partial`. Code applies a ceiling from the evidence: no evidence → `insufficient_evidence`; quotes from one segment → at most `partial`; `observed` needs two different segments. `not_applicable`, `conflicted` and `unknown` pass through. The ceiling only lowers; there is no repair call (`dimension_state_ceiling`).
- **D9 — Signal kinds** are a fixed list in `profiles/call_signals_v1.json` with `status: proposed`. The owner confirms it at Gate 2; it changes only through a new file version.
- **D10 — Nothing judges with a number.** No score, grade, stars, points, marks or percent in `verdict_line` (`has_score_prose`, which also runs `report_claims`). Plain day/month dates such as `10/12` or `10/12/2026` stay valid because `dated_call` verdicts use them.
- **D11 — Cross-call patterns** come after v7 has run on real calls, as counts only, never a score.

### Contract amendments carried by `call-map/1`

Nothing is stored yet, so the version stays `call-map/1`.

- **AUT-416:** `seller_tasks[]` ≤ 6 (the seller's promises: `{id "st…", text ≤ 12 words, due_text ≤ 6 words or null, evidence[1]}`) and `objections[]` ≤ 6 (`{id "ob…", kind, text ≤ 12 words, handling: answered/deflected/ignored/question_back, evidence[1–2], reply[0–1]}`). `kind` is a risk signal kind or `other` (`objection_kinds` in the same profile file). Failure code `call_map_role_mismatch`: seller tasks, claims and the reply cite a `seller` segment; objection evidence cites a `prospect`. The reply is required unless the objection was `ignored` (`call_map_invalid`) and starts at or after the first evidence segment (`call_map_time_out_of_range`).
- **Owner additions of 30 Sep:** `call_purpose {kind: sales/support/onboarding/internal/personal/unclear, evidence[0–1]}`; `prospect_facts[]` ≤ 6 `{key: industry/team_size/company/role, text ≤ 8 words, evidence[1]}` from a prospect; `outcome.next_step_when` as said (≤ 6 words) or null, never converted to a date; `pains[].answer_fit: specific/generic/none`. Call type and confidence are computed by code later, never asked of the model.

### Failure codes

`call_map_invalid`, `call_map_evidence_unresolved`, `call_map_time_out_of_range`, `call_map_phase_order_invalid`, `call_map_reference_unknown`, `call_map_role_mismatch`, `call_map_qualification_invalid`, `call_map_word_cap_exceeded`, `call_map_signal_kind_unknown`, `call_map_money_invalid`, `report_speaker_label_leak`, `ethics_unverifiable_claim_missing`. The same strings in Python (`call_map.py`) and TypeScript (`call-map-contract.ts`); C5 allows one automatic repair for each (B3).

## Alternatives

- A separate AI stage for the call map: rejected, it adds a spend path and a stage code (ADR 0036 D2).
- Letting the model name a call type or a confidence: rejected, a model number reads as a score and is not calibrated.
- Bumping the contract version for each amendment: unnecessary while nothing is stored.

## Consequences

The Overview draws from measurements and quote-backed readings, and the two parsers fail identically. The Python module is pure: it imports only `call_metrics` and `report_claims`, so B2 (prompt and provider schema) and B3 (validation, storage, repair allowlists) build on it without changing it.

## Reversal cost

Low until v7 stores its first `call_map`: the module, profile file and fixture change together. After storage, a field change needs a new contract version and both parsers.

## Evidence

- [AUT-341 plan](/AUT/issues/AUT-341#document-plan) §2–§4; [AUT-416 plan](/AUT/issues/AUT-416#document-plan) §3; [decision brief](/AUT/issues/AUT-341#document-decision-brief) decisions 2 and 7.
- `tests/unit/conversation_intelligence/test_call_map.py` loads `apps/sales-xray-web/tests/fixtures/call-map-v1.json` and checks the signal list against the `signal-kinds:v1` block.

## Owner

CTO owns the architecture; the owner confirms the signal list, objection kinds and the amendments at the Gate 2 review.

## Supersedes

Nothing. ADR 0036 and ADR 0042 stay unchanged.

## Trigger to revisit

The Gate 2 review (signal list, thresholds, amendments), or the first stored `call_map` (version bump rules).
