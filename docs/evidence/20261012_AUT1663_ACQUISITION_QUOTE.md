# AUT-1663: source-bound upload quote check

I's 12 October 06:11 UTC request reports one failing acquisition assertion in
Report candidate `b8c0eb879657d9ba3cee0ee0e8ef3af99fd1e6f5` (PR #470).
The earlier `b00a897` CI success stays separate from that failure and from the
workbench checkpoint `38274d66112ca2ecb343aa865fc317da94c5229b`.

## Cause and repair

The candidate intentionally suppresses legacy missed-chance findings. In the
unchanged fictional Dipak fixture, s1 (`कल timing discuss करूया.`) enters Moments
only through that legacy miss; its other rewatch entry is `must_watch`, while
Report selects only `repeat`. The supported outcome Moment still contains s3
(`तीन बजे ठीक है, please send details.`). The candidate model blob is
`eae27389225fc922f568f921d966f1219fc7f0e9`; workbench model before this repair is
`7bc85cd9d5fbdc196241c5b06331f8d669ebb944`. Fixture blob
`1f2ed0b7965d8a67b32fe2428b12676b235e96ec` matches both sources.

Only `app/acquisition-studio.test.tsx` changes: check the supported original
Commitment quote inside the Moments pillar, then open the real Transcript reader
and assert the exact original s1 quote there. All earlier consent, upload, quote,
transport and same-call assertions and every other test remain byte-identical.
No fixture, product renderer, provider gate or timeout changes.

## Verification

- Original exact-candidate test reproduced the reported failure: one failed,
  112 skipped, at the exact s1 assertion. Earlier assertions passed.
- First repaired candidate attempt hit the unchanged 5,000 ms local timeout;
  the failed log remains retained. It is not counted as a pass.
- Final candidate verification: one passed, 112 skipped, using candidate runtime
  sources and fixtures with only the owned test supplied by a Vite load plugin.
  Default 5,000 ms timeout retained; body 4,910 ms.
- Shared workbench: the same focused case passed (one passed, 112 skipped;
  body 2,990 ms), independently of the candidate result.
- Touched-file TypeScript: `tsc --noEmit --incremental` with the focused
  `tools/acquisition-quote.tsconfig.json` passed. Overlay `node --check` passed.
- Candidate HEAD and runtime/fixture hashes stayed unchanged; the pre-existing
  dirty `next-env.d.ts` and foreign workbench ESLint cache were preserved.

Evidence logs, overlay config, bounded patch and source receipt live in
`/home/acdev/strikes/1663/`. Final receipt and lint result are appended below.
The overlay test SHA-256 is
`c09921f1bd4226dddec54e9c288552b65382b9dee40cfb139c0a6b8eef640234`.

This is local test repair evidence. Candidate integration and its next exact-head
CI verdict remain with the existing candidate owner. No hosted retry, browser,
build, provider activation, account/data mutation or release was performed.

## Final local receipt

Focused cached ESLint, touched-file Prettier and whitespace checks pass.
Source/verification receipt: `/home/acdev/strikes/1663/candidate-quote-source-20261012.json`.
SHA-256: `9f0ac1bc183279ef8f8543e003975f34a22d00e97797ceb02a4b751240a3eb96`.

The original reproduction, local timeout and final passing logs are retained as
`candidate-quote-before-20261012.log`, `candidate-quote-after-20261012.log` and
`candidate-quote-after-retry-20261012.log`; the independent workbench log is
`workbench-quote-after-20261012.log`. Every log hash is in the receipt.

## Updated candidate: original Transcript coverage still required

B's 06:43 acknowledgment and the existing I/CEO coordinator handoff were checked
against the newer candidate `4a7afedeb059df369204e3a394a402e1a714dafa`.
Its normal [Application validation run](https://github.com/authorityclosers/authority-closers-platform/actions/runs/38214948581)
is green. That source checks supported s3 in Moments and intentionally hidden s1
there, but omits the original s1 assertion through the actual Transcript reader.
The candidate Report model is byte-identical to `b8c0eb8` and still drops
matching-summary citations. Green CI on this source does not cover those two
omissions.

The private `candidate-quote-4a7afed-repair.patch` adds only five lines to the
candidate test: open Transcript and assert the exact original s1 quote in its
real reader. All existing assertions and unrelated tests are byte-identical,
including the new Moments-hide assertion, supported s3, consent, same-call and
guarded upload checks. Candidate runtime, fixture and workbench product sources
are untouched. The default 5,000 ms timeout is retained.

The adapted A patch and B's original citation patch both pass
`git apply --check` together on `4a7afed`; no patch was applied there. Thirty-seven
retained/current or immutable historical source, artifact and log pins were
verified. Candidate baseline pins were checked against their original Git
revision, preserving the earlier failure and local timeout records. B's 24-case
model overlay result remains evidence for the unchanged model, rather than a
new model test run here. Final focused checks and the new receipt follow below.

The adapted test passes on the exact candidate runtime with only the private
test supplied in memory: **1 passed, 112 unselected skipped**, body 4,790 ms,
unchanged 5,000 ms timeout. Focused ESLint and both runner syntax checks pass.
The seven pinned runtime/test/fixture files remain byte-identical before and
after verification; no product repair was made by this continuation.

The first strict final-receipt check refused a concurrent candidate worktree
status change. The generated `next-env.d.ts` changed from its pre-existing dirty
bytes to the tracked candidate bytes, while HEAD and all seven pinned product
files stayed unchanged. The refusal and both declaration digests are retained
in `candidate-quote-4a7afed-source-drift.json`; the change's author is not asserted.
The original focused typecheck passed with zero diagnostics. A narrow
incremental typecheck readback verifies the changed declaration context; the
regression and unchanged model suite are not repeated.

The focused incremental typecheck readback passes with **zero diagnostics** in
the tracked declaration context. All authored finite jobs exited.

- Updated A patch: `/home/acdev/strikes/1663/candidate-quote-4a7afed-repair.patch`,
  SHA-256 `b0367fc5e73f498eec32ce62a8d7289de15bb585919879fd30ac5bf285e75f6f`.
- Source/check receipt: `/home/acdev/strikes/1663/candidate-quote-4a7afed-receipt.json`,
  SHA-256 `edb6eda930aef8efb40bb18f18d851346b57a0991ee8b75ea78ce95c23795116`.
- B's unchanged citation patch:
  `/home/acdev/strikes/1677/candidate-summary-repair-20261012.patch`, SHA-256
  `1a11da84f7b865716d5a81cf45ddf87f8fa615c4e59ac22f47672f63f697cac3`.

The existing coordinator → Platform Engineer/AUT-1783 route must integrate
both patches and return normal CI for the resulting exact source, preserving
legacy suppression and the SVAL/runtime holds. This private test overlay and
the unpatched candidate's green CI are separate receipts. No branch/PR write,
hosted retry, browser/build, provider activation, account/data mutation or
release was performed. The foreign workbench ESLint cache remains preserved.
