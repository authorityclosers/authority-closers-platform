# AUT-648 — C5 preparation provenance (8 October 2026)

Source: main `bc61dbfaca369ee81f22a1e4097a5783a12d71a2`; branch `task/sales-xray/648-c5-run-provenance`. Evidence filename follows the card; actual work date is 2026-10-08.

The initial `ConversationInferenceTask.intent.input.prompt_provenance` is reachable through the task's `run_id`. It contains five bounded values: `prompt_revision`, `template_sha256`, `provider`, `model`, `output_language`. No second store, column, migration, historical update, prompt text or call text is added.

`coaching_template_sha256` hashes the exact UTF-8 system template produced by the existing dispatch builder, including effective instruction, overview, language, compiled pack and profile material. The call-bearing user message is excluded. `input_sha256` and `payload_sha256` keep their existing payload meanings. Provider request, schema and report bytes are unchanged.

A repair retains its own initial intent and the base compiled C5 template receipt. Its dynamic repair context (including source speaker identifiers) is bound by its separate payload hash. It does not replace the original run's receipt. Exact-byte reconstruction uses `PreparedTaskInput.from_dict`, retains saved provenance without consulting current settings, and accepts legacy metadata without fabricating a receipt. Missing historical provenance means **revision unknown**, even when the recipe is `qualitative-coaching-v1`. Existing dispatch intent/digest checks continue to refuse reconstruction drift. The 9 October review repair below permits comparison with legacy queued intents without backfilling or relabeling them.

## Fictional before/after

Before/legacy: no `prompt_provenance`; effective revision unknown. The legacy reconstruction test round-trips that metadata unchanged.

After, the same one-segment fictional input through the preparation test helper:

| Effective revision | Template SHA-256                                                   | Provider / model           | Effective language |
| ------------------ | ------------------------------------------------------------------ | -------------------------- | ------------------ |
| coaching-v3        | `381b3aaacacd5a043bc5f6e49a1366dc4a40f48d0bac83e9b5ba3c6b7fed44b4` | groq / openai/gpt-oss-120b | en (default)       |
| coaching-v5        | `e7df77e258a03f0d599f6caea73c551c681dba2dd73d64d08f409736eb13d63e` | groq / openai/gpt-oss-120b | en (default)       |

Tests show different fictional call text/source hashes keep the same template hash; revision, instruction, profile and language changes alter it. Groq, Gemini and OpenAI route identifiers and all supported output languages are captured. Queued, failed and separate repair intents retain their receipts; malformed/text-bearing receipts are rejected.

## Verification

- Baseline required suite: **156 passed in 5.53s**.
- `.venv/bin/python -m pytest -q tests/unit/conversation_intelligence/test_reports.py tests/unit/conversation_intelligence/test_inference_tasks.py tests/unit/conversation_intelligence/test_processing_plan.py`: **163 passed in 8.61s**, exit 0.
- `.venv/bin/python -m pytest -q tests/unit/conversation_intelligence/test_coaching_v5_depth.py tests/unit/conversation_intelligence/test_coaching_v7_prompt.py tests/unit/conversation_intelligence/test_coaching_v7_output.py tests/unit/conversation_intelligence/test_retained_c5_recovery.py`: **111 passed in 45.20s**, exit 0.
- Existing v1–v5 historical prompt pins, v4–v6 prompt/response-schema/generation-schema pins, and v4–v6 stored-report pins pass unchanged. The whole-file reports source pin was updated solely for the new fingerprint helper. V6/v7 runtime refusal checks pass.
- `uv run ruff format --check packages/python tests`: **1055 files already formatted**; `uv run ruff check packages/python tests`: **All checks passed**; `uv run mypy packages/python`: **434 source files, no issues**. All exit 0.
- Gate admitted the sales-xray lane, main running; continuation check passed. Open PR file claims had no overlap. Initial dev URL check returned HTTP 302 (login); no customer content was read.
- Initial head `7bfe6478523b50cab84c373425826b59bcbe7971`: GitHub checks green, observed on 9 October. CTO requested changes on that head; it is not approved. The repaired head needs fresh CI and CTO review.

## CTO review repair (9 October 2026)

At source `7bfe6478523b50cab84c373425826b59bcbe7971`, new fictional regressions reproduced **4 failed, 52 passed in 11.10s**: one queued legacy C5 intent was refused and legacy speaker attribution returned null across Groq, Gemini and OpenAI. Receipt drift was already refused.

`input_metadata_for_saved_intent`, beside `PreparedTaskInput`, returns fresh rebuilt metadata with only `prompt_provenance` omitted when a saved C5 input lacks that key. The worker hashes the rebuilt intent using this comparison metadata; speaker attribution uses the same helper. All other input/intent fields and saved digests still match exactly. If provenance was saved, its template hash must match exactly. No saved intent is modified, and historical revision remains unknown.

- Combined required suite plus worker and speaker-basis regressions: `.venv/bin/python -m pytest -q tests/unit/conversation_intelligence/test_inference_worker_stages.py tests/unit/conversation_intelligence/test_speaker_report_basis.py tests/unit/conversation_intelligence/test_reports.py tests/unit/conversation_intelligence/test_inference_tasks.py tests/unit/conversation_intelligence/test_processing_plan.py`: **219 passed in 7.69s**, exit 0. Legacy worker admission and all three speaker-basis formats pass; changed template receipts remain refused. Existing v6/v7 worker gates remain refused before reconstruction.
- After strengthening the worker's saved-intent immutability assertion, its suite passed again: **15 passed in 7.81s**, exit 0. The four pinned-contract/recovery files listed above passed again: **111 passed in 33.92s**, exit 0.
- Ruff lint passed on the five changed Python files; mypy passed on the three changed source files. Ruff formatted two files and left three unchanged.
- Dev URL still returns **HTTP 302 (login)**. This is availability evidence only; the repaired source is not deployed or activated.
- Fresh repaired-head CI, CTO review, watchdog merge and deployed source verification remain required. No polling timer, live provider call or data mutation was used.

## Dev check and remaining release evidence

At https://salesxray-dev.authorityclosers.com, the report UI and generated bytes stay unchanged. On the deployed dev source revision, run the two mocked/fictional pytest commands above; exit 0 means pass, 1 means assertion failure. No live provider call is required.

After review and watchdog merge, record the deployed dev SHA and rerun this same fictional path, then verify staging through the release train. Never mark the task done on approval alone. This run has no merge, deployment, provider activation or production data change.
