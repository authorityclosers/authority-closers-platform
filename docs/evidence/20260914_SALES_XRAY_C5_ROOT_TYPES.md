# C5 root-type and literal-quote instructions

Production release `fc7dc8687ba137f8bab35a99f9734db84093a460` completed C2 and C4
for the approved 60-second excerpt, then rejected C5. The privately exported
Gemini response finished with `STOP`; it was not a truncated response.

Offline replay reproduced `report_findings_invalid`: `objection_analysis` and
`closing_analysis` were objects containing empty evidence instead of lists,
and `verdict` was an object instead of a string. A separate source check found
one partially transliterated quote among fourteen spans. The actual response
remains rejected. No corrected copy is published or presented as provider output.

The prompt now states these root types, asks for empty lists when no supported
finding exists, and requires exact reuse of supplied evidence objects. It does
not relax the parser or convert invalid provider content. A narrow operational
allowlist addition retains `conversation_report_findings_invalid`; arbitrary
exception text still maps to a content-free generic code.

The original request was reproduced byte-for-byte from the frozen production
profile, transcript and C4. The new instructions change only C5 input identity;
the actual C4 input reproduces unchanged and the C2 payload remains intact.
The response cap stays at 3200 tokens. A fresh approved plan and live provider
test are still required; prompt instructions do not guarantee future output.

## Validation receipts

All receipt paths below are under `D:/AC-authority-closers-release-audit/`.

- `python -m pytest -q tests/unit/conversation_intelligence/test_report_structure.py
  tests/unit/conversation_intelligence/test_inference_failure_diagnostics.py`:
  **25 passed** in 3.10 seconds. Log `peer-c5-root-types-focused-20260914.log`,
  SHA-256 `3dc2616585a8877158da3ff919310e3852192417046c642f9d0015ed5981d46a`.
  JUnit `peer-c5-root-types-focused-20260914.xml`, SHA-256
  `3eb2233a5de83b4bc948b5fd9e162267f5f571f660fb2ed4196077f9547ba784`.
- Actual request replay: `peer-c5-root-types-offline-replay-20260914.json`,
  SHA-256 `16a3e9af99b0e32f26e9a79727d8664ff574bf64dae64cf7adbe177064e092fc`.
  New payload is 18253 bytes; actual old C5 input and unchanged C4 input matched.
- Ruff lint, Ruff formatting check and `git diff --check` passed for the four
  changed Python files. No storage, native decoder or runtime guards changed.
- Expanded conversation unit run: **777 passed, 31 failed, 19 skipped** using
  the default Windows temporary directory. Its ancestors include
  `C:/Users/Suyash/.git`, triggering storage-outside-repository guards.
  This failed run is preserved as `peer-c5-root-types-conversation-20260914.*`.
- Rerun with a new external `--basetemp`: **809 passed, 1 failed, 17 skipped**.
  The remaining failure is
  `test_actual_offline_native_preflight_measures_original_samples`; native
  preflight reported that audio length could not be verified. It is not claimed
  passing or resolved. Log `peer-c5-root-types-conversation-external-temp-20260914.log`,
  SHA-256 `224cbdd32126109bb9df0b64fc94f3f4575bf5898ea43553844555843d1d58d0`.
  Linux CI remains required before release.

Synthetic regression coverage includes wrong object/array/string types, empty
evidence placeholders, literal mixed-script quote rejection, truthful empty
collections, C5-only input changes and fixed output budget for Groq and Gemini.
Private source/response content was not copied into repository fixtures.

The C4 review also records proposals about missing turnover-unit/trend
uncertainty and a compressed margin qualifier. These are not approved labels,
automatic retraining, or claims that the final report is ready.
