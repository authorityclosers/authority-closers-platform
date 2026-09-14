# Sales Xray production quality follow-up — 2026-09-15

Base: 724f3ab549e1837bc0f5ed49aa298d4fd0f308a1. This candidate combines the guest recovery action, editable provider/model stage cards, larger customer typography, and complete source transcript context for coaching. Each originating leaf retains its tests and evidence.

The guest reset handler accepts an optional preservation policy. React click bindings now explicitly call reset with no policy rather than passing a MouseEvent as that policy. This fixes the two TypeScript errors introduced by the recovery leaf; behavior for removing a selected file and starting another completed call stays the same.

Local integration validation on this checkout:
- Sales Xray TypeScript: pass.
- Acquisition workflow and style integration: 34 tests passed.
- Coaching source context, extended budget, report structure: 54 tests passed.
- Prettier for acquisition source/styles and git diff check: pass.

Not a production verification claim. Live baseline when recorded: 8fe18b14. Fresh production 20:53 recording 3e401eda completed and has a retained report; original Dipak recording 998af67e remains held after C5 attempt 649ca180. That failure requires diagnosis, and the new full-context prompt requires one real bounded C5 validation after deployment.
## Retained Gemini response compatibility

Original Dipak continuation 649ca180 completed at the provider with STOP (8,972 input / 4,675 output tokens), but the app rejected eight overview citations because they were single objects rather than arrays. The adapter accepts only an object with exactly segment_id, quote, start_ms and end_ms as a one-item citation collection. It leaves the raw response untouched and runs the same source, timestamp, reference, chronology and claim validators. Unknown fields, malformed shapes and fabricated source data remain errors. This is a lossless representation adaptation, not a rewritten report or an official scoring approval.

44 overview and compatibility tests passed. An initial test fixture incorrectly assumed a non-null diagnosis; the corrected fixture explicitly supplies it and exercises source rejection. Ruff lint/format pass. Whole retained production-response replay remains to be recorded independently before a live recovery claim.

Deepgram integration also passed 139 targeted tests; 17 POSIX ownership tests are skipped on Windows and remain required in Linux CI. Python types pass for all 75 conversation source files. Admin provider/settings integration: 18 tests and TypeScript pass.