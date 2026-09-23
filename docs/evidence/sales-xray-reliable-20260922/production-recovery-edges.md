# Production recovery edge cases — 23 September 2026

Production release `0ea451441670ec5962a026deb6bbcc329e693eb3` was installed through
the canonical installer after an application-owned pause and a SELECT-only
drain proof. API, web and native artifact identities matched the approved release.
The existing owner account was reached through the Authority Closers Chrome
profile. Provider revision 7 was appended and activated through the source-owned
admin service, and the owned pause was resumed. The approved production budget,
expiry, retention, consent and provider limits were preserved.

This deployment is **not** evidence of universal end-to-end success. A real-provider
production test using fictional audio exposed the following additional cases.

## Learner read denials

An old unavailable submission returned 500 on the learner surface. Its ownership
service correctly raised `ConversationNotFound`, but the new shared read-only
learner dependency did not translate that domain exception. The mutation and
standalone read paths already translated it.

The learner read dependency now translates the exception after the account
transaction unwinds. Regression requests cover progress, report, DOCX, transcript,
waveform and audio. Before the fix, five returned 500; DOCX already handled the
denial. All six now return private, non-cached 404 responses and unwind the
transaction. No ownership or retention check was relaxed.

## Independent administrative controls

While the old processing approval was expired, execution-state GET returned 200
and budget GET returned 503. `Promise.all` discarded both results and hid pause
controls. Each response now validates and updates its own state independently.
Unavailable or malformed budget data hides budget editing and shows a specific
message while confirmed execution controls remain usable. Execution failures
still disable unconfirmed mutations.

Both new expiry/malformed-budget tests failed before the fix and passed afterward.
The complete execution-controls test file passed six tests.

## Returned C5 evidence-reference errors

The production fictional call completed ElevenLabs transcription and Gemini fact
extraction. Gemini then returned a coaching response with milliseconds in three
character-offset references and an out-of-range fourth reference. Strict source
validation correctly rejected it, preserving the returned bytes. However, the
failure was collapsed into a generic diagnostic not eligible for the already
budgeted single repair.

`report_evidence_invalid` now has its own content-free diagnostic and is eligible
for the existing single C5 repair only when a matching returned response receipt
exists. Its repair instruction distinguishes character indices from timestamps
and prefers supported compact segment selectors. Validation, cost bounds,
request counts, receipt requirements, original responses and historical prompt
bytes remain unchanged. An unproven delivery or generic unknown error is not
silently retried.

The PostgreSQL scheduler/worker regression exercised missing-field and
timestamp-as-offset failures through one repair to C6: two passed. It proves
exactly two C5 tasks, preserved original returned evidence and a valid resulting
report. The focused report/repair suite passed 99 tests.

The historical production test was recovered separately through the existing
retained-C5 correction CLI, with four hash-bound citation-array corrections and
zero new provider calls. Its corrected draft renders after a full reload and is
listed as report-ready in the account library. This assisted recovery is not a
clean first-pass pipeline success. Original bytes and failed task state remain
available; the draft is marked as a Codex proposal, not human-adjudicated scoring.

Private receipts, exact response hashes and fictional report bodies are retained
outside Git. No customer audio, secrets, response text or operational SQL edits
are included in this evidence file. Independent read-only review found no blocking
defects in these three fixes. Exact-source CI and deployment of this follow-up
remain pending until separately recorded.

## Versioned coaching guidance

New processing plans select `coaching-v3`. It prefers whole-segment references
and defines excerpt indices as Unicode code points, explicitly excluding audio
timestamps. It also prohibits invented product terms in suggested coaching
phrases; unknown details require a question or conditional placeholder. This
addresses an unsupported daily-practice-duration assertion in the fictional
production draft as well as the citation failure.

The v1 and v2 prompt bytes remain unchanged, verified with hashes captured before
the edit. Saved plans continue to select their recorded revision. V3 passes
serialization, checkpoint and retained-input reconstruction checks. Strict
evidence validation, commercial-state wording and provider limits are unchanged.
Independent read-only review found no blocking compatibility defects.

Validation after these changes: 101 focused unit tests; 27 PostgreSQL HTTP and
processing-plan tests; three historical retained-recovery PostgreSQL cases;
Python lint, formatting and types (302 source files); admin formatting, lint,
types and six execution-control tests. V3 retained recovery is also tested
against PostgreSQL before freezing the release.
