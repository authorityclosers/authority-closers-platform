# Mixed-script request preparation — 14 September 2026

The retained 144-segment Hindi/English call failed C4 request preparation at the hosted 16,000-character setting. The planner packed characters while the following limit counted UTF-8 bytes. Its retained sixteen source-linked facts also failed C5 at the approved 1,800-token output cap under the shared historical 8,000-token limit.

This leaf starts from `c6fb8a8fa73fcc7056abd4b3f217fcc76d430d2b`. It changes four Python source files and adds one regression module. It does not change UI, authentication, migrations, provider selection or activation state.

## Result

- C4 packs complete native segments under both the existing character ceiling and a UTF-8 byte ceiling. The source envelope, maximum possible chunk index and native wrapper reserve are included. An individually oversized segment is refused, never split or rewritten.
- Only Gemini `gemini-3.8-flash` coaching uses a 32,000 combined allowance: UTF-8 input bytes + approved output tokens + 128 framing allowance. Input bytes are a conservative token allowance, not a measured provider token count. Other models and C4 retain their existing 8,000 heuristic ceiling.
- The report builder, saved task reconstruction and fixed provider broker run the same native-envelope check. The broker takes the stage from its approved stage, not from payload text. A matching digest does not allow an oversized body through.
- Output caps stay C4 1,400 and C5 1,800 for the release configuration. The exact ₹5 request reservation and total approved budgets remain separately enforced.
- No report instruction, fact, quote, timestamp, profile field or overview section was removed. Existing ASCII request bytes are unchanged. C2/transcription inputs and recipes are unchanged.

## Tested here

The original eight synthetic mixed-script regressions failed before the fix. The final targeted run passed **118 tests, zero failures, zero skips** in 2.14 seconds. It covers Hindi/Marathi/English with JSON escaping, 144-segment coverage, large metadata, both Gemini models and Groq, allowed output caps, native task reconstruction, strict qualitative report parsing, 64-fact C5 input, exact byte boundary, and oversized broker rejection with one explicitly simulated child dispatch. Ruff, formatting and strict mypy passed for the changed source.

The retained call was read locally, with network sockets disabled. Its native transcript and legacy facts were not modified. Legacy facts were mapped in memory and all literal evidence/timestamps were revalidated; this created no new checkpoint or provider result. Before: both C4 and C5 preparation failed. After: four C4 requests (largest old heuristic bound 7,904/8,000) and one C5 request prepared. C5 input is 18,398 UTF-8 bytes; combined byte allowance is 20,326/32,000. Its facts, system instructions and embedded profile hashes exactly match the prior code's accepted 1,400-output preparation.

The baseline input receipt names `11cf7ea42d55af33cdd63e17959403789cd8e7e1`, the release coordinator's intervening DB-test-only commit. It records the four source-file hashes, which are the unchanged pre-fix versions. The after receipt records the base HEAD plus the tested dirty source hashes; the receipt index binds those hashes to this leaf.

## Cost bound and limits

Google lists Gemini 3.8 Flash at $0.75/M input and $3.75/M output, including thinking, through 31 December 2026. At the release's ₹100/USD planning assumption, even 32,000 input tokens **plus** 1,800 output tokens is ₹3.075 before tax, below the ₹5 reservation. This deliberately overstates the permitted combined envelope. It is a planning bound, not actual usage, an exchange-rate claim or evidence of a funded/free allowance. [Official model/pricing details](https://ai.google.dev/gemini-api/docs/latest-model), [pricing table](https://ai.google.dev/gemini-api/docs/pricing).

There were **zero external provider calls and zero transcription calls** in these checks. Larger inputs still fail closed; there is no automatic shortening, larger retry, extra output allowance or paid fallback. A 1,800-token cap can still end in an incomplete model answer, which remains rejected. Actual report generation quality, usage, staging browser proof and production publication require the release coordinator's hosted test.

## Receipts

Portable evidence is in `docs/evidence/mixed-script-prompt-budget-20260914/`: before/after input receipts, original failing JUnit receipt, final passing JUnit/log and a hash index. Private diagnostic script and intermediate logs remain outside Git under `D:/AC-authority-closers-release-audit/`. Intermediate checks include one existing assertion expecting the literal phrase “Do not score” during a temporary wording experiment; the final source restores the entire original report instruction text.

Reproduce the targeted suite with the project environment:

```powershell
$env:PYTHONPATH = "$PWD/packages/python;$PWD"
python -m pytest tests/unit/conversation_intelligence/test_mixed_script_prompt_budget.py tests/unit/conversation_intelligence/test_reports.py tests/unit/conversation_intelligence/test_report_overview.py tests/unit/conversation_intelligence/test_inference_tasks.py tests/unit/conversation_intelligence/test_gemini_tasks.py tests/unit/conversation_intelligence/test_broker_router.py -q --tb=short
```
