# AUT-1677: bounded per-call Coaching response recovery

The Report's optional call Coaching reader previously buffered the entire reply
with `Response.text()` before checking 128,000 decoded characters. An oversized
stream could keep consuming memory until the existing scope deadline, and an
adapter ignoring abort could keep reading after the view had recovered.

The owned reader now counts UTF-8 bytes as chunks arrive, rejects a declared or
streamed body above 128,000 bytes, and cancels/releases its reader on success,
failure or scope loss. Cancellation cleanup does not await an uncooperative
adapter. Invalid UTF-8 is unavailable instead of silently changing visible text;
valid Devanagari split across chunks remains intact. Existing call/person/tenant/
session/source/report and native quote/timing checks remain enforced. The
Report's existing unavailable notice and retained-report fallback handle failure.

Validation on the existing strike branch, base `3054a3f`:

- All 80 focused cases pass across `report-call-coaching-stream.test.ts`,
  `report-call-coaching-client.test.ts`, `report-call-coaching-read.test.tsx` and
  `report-preload.test.ts`. Nine stream cases cover early overflow, declared size,
  Indic byte counting, split UTF-8, corrupt encoding, stalled/late reads and
  stalled/rejected cancellation. Existing source, privacy, media and saved-read
  checks pass alongside them.
- The pre-fix run admitted oversized declared/Indic bodies and corrupt UTF-8;
  those assertions failed. Its two stream cases also failed with locked-body
  cleanup errors, and the successful split-text case left its body locked. The
  final nine-case stream proof passes, including actual cancel/lock assertions.
- Incremental TypeScript, cached changed-file ESLint, Prettier and diff checks
  pass. No dependencies or shared/sensitive paths change.
- A private, count-only offline check built the current Python account-projected
  call Coaching envelope for all 13 retained C5 reports; three have no C5.
  Maximum encoded body: 14,820 bytes, zero oversized/failed cases, zero providers.
  This is projector compatibility, not authenticated API or production proof.
  Receipt: `/home/acdev/strikes/1677/coaching-wire-size-receipt.json`.

Committed shared-dev screenshots and their exact source receipt are recorded in
`/home/acdev/strikes/1677/NOTES.md` after the shared refresh. The existing
populated call Coaching fixture checks retained source/lesson/media behavior;
stream failure recovery is proved by the focused response-reader tests.

Production Report acceptance remains with H/QA; saved-call route adoption stays
with A. Company/outcome persistence still awaits the reviewed migration and
authority chain. No provider activation, production/staging write, deployment,
manual merge or production readiness claim.
