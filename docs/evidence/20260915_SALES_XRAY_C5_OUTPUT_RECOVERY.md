# Bounded recovery for the truncated Gemini coaching response

## Observed failure

The retained production call reached C5 using its saved C2 transcript and four
C4 fact checkpoints. Run `d8d12549-4f38-4f4e-b98a-39f734a07650` received a valid
Gemini envelope with `finishReason=MAX_TOKENS`, 3196 candidate tokens and a 3200
output cap. The embedded report JSON was incomplete; the adapter correctly
rejected it as `conversation_gemini_response_incomplete`.

Private diagnosis is outside Git:
`D:/AC-authority-closers-release-audit/production-b4-dipak-c5-diagnosis-20260915.json`.

## Change and bounds

- Only `gemini / gemini-3.8-flash / C5` can receive an explicitly approved output
  cap above 4000, up to 8000. Other routes retain their 4000 ceiling.
- Both recording-specific approvals and acquisition templates require a fresh
  paid reservation of at least 1000 paise for that extended output.
- The conservative Flash C5 input-plus-output envelope becomes 64000 only when
  the explicit cap exceeds 4000. Existing approvals retain their 48000 envelope
  and original 3200 allocation; their request hashes remain unchanged.
- Durable plan derivation, prepared input reconstruction and the Gemini request
  agree on the exact route-specific cap. An extended request creates a new C5
  input hash while preserving transcript, facts and coaching profile.
- Prompt wording, response schema, literal quote validation and rejection of
  incomplete provider responses are unchanged. There is no automatic larger
  allowance, provider retry, transcription replay or aggregate budget increase.

The release coordinator owns fresh immutable approval/registry packets and
deployment. Existing frozen approval artifacts were not edited by this change.

## Validation receipts

Checkout base: `b4ebfcf558951d33f68e2aa39f1f7ae10e5ba4c4`.

- Focused tests: **161 passed in 2.88s**. Command: `python -m pytest` followed by
  these files under `tests/unit/conversation_intelligence/`:
  `test_extended_coaching_budget.py`, `test_gemini_tasks.py`,
  `test_activation_contract.py`, `test_processing_plan.py`,
  `test_mixed_script_prompt_budget.py`, `test_inference_tasks.py`,
  `test_report_overview.py`.
  JUnit: `D:/AC-authority-closers-release-audit/peer-c5-8000-focused-v2-20260915.xml`.
- New regressions exercise approval cost/route limits, exact input-envelope
  boundaries, durable request shape, unchanged old allocations, payload
  reconstruction, preserved facts/profile and rejection of MAX_TOKENS output.
- `python -m mypy packages/python/ac_platform`: **290 source files passed**.
- Ruff check, format check of all nine changed Python files, and
  `git diff --check`: **passed**.
- A retained-input replay verified all five checkpoint hashes, all 152 covered
  segments, all 38 observations and the complete profile. Both message bodies
  are byte-identical before and after the cap change. The old input hash is
  `367227dd3c4901154e40b961690d0808ae76a1a008037995a464d42f6c0b8e80`;
  the extended request hash is
  `20bbc9ccd92d7f11d31198b2a53a3531d0cd73840a58962255fcefe2f9b6f084`.
  The payload is 45264 bytes; conservative units are 51244 of 64000.
  Script and JSON receipt:
  `D:/AC-authority-closers-release-audit/peer-c5-8000-full-call-proof-20260915.py`
  and its `.json` companion. No call text is copied into Git.

The first focused run had four new-test fixture failures because strict UUID
validation was given JSON-mode strings. The fixture now retains Python UUID
objects; the full focused rerun above passed. No production validator was
weakened to resolve those fixture failures.

## Limits of this receipt

This leaf made zero provider calls and no production writes. It proves input
preservation and finite authorization bounds, not provider output quality,
actual billing, staging/production deployment, or the final browser report.
Those checks belong to the coordinated release after fresh activation.
