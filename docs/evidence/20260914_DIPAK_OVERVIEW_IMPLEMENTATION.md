# Dipak overview implementation — 14 September 2026

Built from the owner's ten-page `REPORT-Detailed 14 points.pdf` reference, not
its example values. The exact mapping and boundaries are documented in
`docs/contracts/SALES_XRAY_DETAILED_OVERVIEW_V1.md`.

The actual standalone/LMS overview now shows strengths, ordered fixes, selected
moments, possible concerns, a before/change/after view, qualitative skills and
one target/drill. Older saved reports keep their existing findings and explicit
missing states. English controls preserve literal Hindi/Marathi/English content.
The additive backend schema and C5 prompt supply distinct fields; the UI does not
manufacture them by relabeling broad findings. Numeric publication remains held.

## Evidence scope

- Vitest: 90 passing tests in 12 files, including source binding, strict schema,
  all detailed fields, legacy compatibility, source replay and print restoration.
- Conversation Python suite: 550 passes, one Windows/POSIX ownership skip.
  Native AudioAtlas numerical tests are included after verified binary/source reuse.
- Standalone optimized build, static export and embedded learner build passed.
- Scoped ESLint/TypeScript, Python Ruff and mypy passed; exact command receipts
  accompany the packet.
- Structured browser: actual built app, shared synthetic report, real media
  playback, source seek, keyboard disclosure and widths 1280/390/320 passed.
  API responses are intercepted. No external provider request.
- Legacy browser: same compiled app, existing synthetic navigation/recovery
  fixture passed. Its media.play recovery is deliberately substituted and labeled.
- Private saved-call preview: original audio replay and all 144 stored transcript
  segments verified; saved findings rendered in the new layout; zero new provider
  calls. Fifteen-page PDF rendered and visually checked, all overview labels present.
  Private audio, report, screenshots and PDF remain outside Git.

- Actual disposable PostgreSQL: nine report/storage/pipeline tests passed in
  107.21 seconds; seven consent/scheduler/ownership/erasure plan tests passed in
  152.55 seconds. These exercise synthetic provider responses, not real inference.
- Actual local HTTP/browser: AC password identity, imported saved-report/upload,
  and durable C2–C6 report/playback cases passed. No API route is mocked. The first
  run passed two cases and failed the new detailed-field locator, which searched
  for an exact string despite the visible “Why it matters” prefix. After correcting
  that locator, the durable case passed in 41.93 seconds. Its receipt explicitly
  verifies new overview fields arriving through the real API.

The portable XML, build logs and browser/network receipts are in
`docs/evidence/sales-xray-dipak-overview-20260914/`. The receipt index gives actual
byte counts and SHA-256 hashes. Production and staging publication of this packet
are not yet claimed. Google OAuth and external provider quality are not proven by
the local password-identity and synthetic-worker tests.

## Failures found and corrected

The first Python run used a temp directory under a Git ancestor, which correctly
triggered private-storage protection. A fresh external test root resolved that
environment issue. Tests also caught the new prompt being appended after the
broker's trailing Profile JSON; moving the format instructions before it preserved
strict profile validation. Initial receipt: 32 failures, 501 passes, 17 skips;
the final run is the 550-pass receipt above.

The first structured browser fixture omitted its recording ID and then used an
obsolete audio selector. Both test-fixture defects were corrected; source-ownership
and real-playback assertions remain enforced. An interrupted environment discarded
several running handles before completion; those attempts are not counted as passes.

## Remaining release work

The release coordinator owns combined CI, immutable image promotion and hosted
activation. The guest acquisition source-to-worker/report bridge is the next Sales
lane; it is not implemented by the overview presentation. New-format provider
quality/completeness, authenticated hosted upload, deletion/IDOR, canary and rollback
must be verified before claiming the complete public product. Existing local real
call drafts remain pending Dipak/Suyash review; this change is not a new benchmark.
