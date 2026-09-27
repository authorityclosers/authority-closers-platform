# Reconstruct a saved C5 repair input exactly

Read-only diagnosis of historical staging C5 failures found a separate reconstruction defect: `_rebuild_prepared_c5_input` rebuilt only the base coaching request. A saved request containing its one permitted `repair` would therefore be compared against the wrong input digest during retained-response recovery.

The helper now validates the stored `C5RepairIntent` and applies the existing `repair_coaching_input` function before returning the reconstructed bytes. The recovery caller still requires the exact dispatched input digest and the existing strict report validation. No provider request is made, no extra attempt is authorized, and no advice, evidence order, indexes, or historical prompt bytes are rewritten.

Validation:

- New regression tests failed before the patch: Gemini and Groq reconstructed base bytes instead of repair bytes; an invalid second repair was silently ignored.
- All three new tests passed after the patch, together with the existing retained-recovery and extended-budget suites: 31 passed.
- Tests verify exact payload and SHA equality, input immutability, and rejection of attempt 2.
- Ruff formatting/checks passed.

This patch does not itself recover the two historical calls. Their saved repair outputs still fail the report contract, and both have already consumed the one automatic repair. The observed nonzero focus indexes are not uniformly one-based; silently changing them or reordering improvements would change coaching priority. No such correction or additional paid retry was performed.

Unrelated coaching-v6 changes in the working tree are excluded from this repair's commit. A deployment and canonical recovery eligibility check are separate requirements.
