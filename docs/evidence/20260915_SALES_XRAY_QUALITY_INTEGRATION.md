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

## Integrated report and Admin follow-up

The explicit overview-array prompt and audited Admin Open report route are integrated. Local focused validation passed: 26 backend tests, 5 Admin UI tests, Admin TypeScript, all 659 Python files formatted, Ruff lint, and mypy on all 294 source files. An independent combined C5 check passed 95 tests and rejected forged citations at all 11 overview evidence paths.

Read-only replay of the original retained 649ca180 response against the integrated candidate passed the full coaching validator. The exact original task input SHA was reconstructed and matched; no database write or external provider call was performed. This proves structural/source validation, not publication or perfect coaching quality. Separate semantic review identified improvement opportunities in attribution, chronology, evidence coverage and plain language; the new full-context prompt still needs a real output review.

The first combined Linux run, 34900064404 at 89df607, passed frontend, capacity and Python deployment gates but failed Python shards using an outdated simulated C5 response plus a formatting check. The authority method formatting is corrected here; the synthetic provider/input expectations are being repaired independently without relaxing production validation. Sales Xray web-image run 34900069538 passed, but the failed core candidate was not deployed. The currently deployed 724f baseline is healthy on staging and production. A new complete green candidate and authenticated/public browser checks remain required.
