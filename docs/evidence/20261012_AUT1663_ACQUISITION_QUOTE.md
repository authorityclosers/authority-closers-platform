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
