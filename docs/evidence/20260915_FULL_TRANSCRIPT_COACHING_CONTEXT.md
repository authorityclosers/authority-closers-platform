# Full source context for C5 coaching

A real production C6 report passed its structural and literal-evidence checks
but missed earlier questions and attempts that its selected C4 observations did
not retain. Coverage IDs alone did not give the report writer those source turns.

C5 now receives every normalized C2 turn, with exact ID, speaker label, start/end
milliseconds and native-script text. A lossless column/row table avoids repeated
JSON field names. C4 statements and uncertainties remain present. Their repeated
quoted text is represented by literal character ranges into the complete source
table; the report parser still requires exact quotations and timestamps.

The input retains both the original C2 payload digest and normalized transcript
digest. Reconstruction verifies ordered coverage and the table digest. Result
binding compares the complete context against the actual retained C2 payload.
Legacy inputs without the new context marker remain readable. No source turn is
silently truncated: oversized requests fail before dispatch.

Generic instructions distinguish attempted actions, proposals, agreements and
confirmed outcomes. They credit earlier decision-maker questions and joint-call
attempts, distinguish absence/busy from refusal, and require recommendations to
acknowledge work already attempted. They request plain, direct coaching and forbid
vocal/psychological certainty from this transcript-only input. Compact instructions
preserve the small synthetic 3200-output cases on the existing Groq/Pro limits.

## Bounded cost and checkpoint reuse

Only the previously authorized extended Flash C5 envelope changes from 64,000 to
96,000 **total** conservative units. At 8,000 maximum output tokens, that allows
87,872 UTF-8 input bytes plus 128 overhead. The unchanged frozen price basis
($0.75/$3.75 per million input/output tokens, INR100/USD) gives a maximum of
960 paise, below the existing 1,000-paise approval. This uses one input byte per
token conservatively; it is not an actual provider token count or invoice.

Other routes and the normal <=4000-output Flash envelope keep their limits. The
existing extended-output approval still requires the 1,000-paise bound. Output
limits, provider choice, profile, numeric-publication hold, C2 and C4 are unchanged.
Only C5 input identity changes. No saved report or approval is rewritten here.

## Evidence produced here

`D:/AC-authority-closers-release-audit/peer-full-context-final-20260915.xml`:
**143 tests passed in 2.63 seconds**. These cover complete source/quote recovery,
tamper rejection, actual-C2 result binding, unchanged C2/C4 request preparation,
provider-envelope reconstruction, legacy report validation, the exact total/cost
boundary and rejection rather than truncation for oversized source input.
Ruff lint/format, targeted mypy on four changed source files and diff checks pass.

Metadata-only local proof and replay script:
`D:/AC-authority-closers-release-audit/peer-full-context-proof-20260915.json`
and the adjacent `.py` file. Both retained private checkpoint sets pass:

| Case | Complete turns | C4 statements | Input bytes | Total units | Cost upper estimate |
|---|---:|---:|---:|---:|---:|
| New production C6 source | 147 | 40 | 70,997 | 79,125 | 833 paise |
| Original held-call source | 152 | 38 | 71,115 | 79,243 | 834 paise |

The proof verifies unchanged source artifacts, exact C2 payload hashes, all C4
payload hashes, lossless recovery of every original evidence excerpt and fresh
C5 envelope reconstruction. It performs no provider call or database write.

Earlier targeted runs exposed the obsolete 64k assertion and repeated-quote
transport assumptions, plus prompt overhead on the small Groq/Pro fixtures.
They were corrected through the new bound test, lossless reconstruction assertions
and compact instructions; provider limits were not relaxed for those routes.

This is implemented and tested locally, not evidence of deployment or improved
model output. A new authorized C5/C6 must be generated and reviewed after release.
The real-call contextual findings remain proposals for Dipak/Suyash review;
no human adjudication, automatic retraining or holdout access occurred.
