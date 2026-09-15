# Full-context C5 fixture compatibility

Base: `89df607af8ae3764ffe9a34d53b6150481a7b80e`.

The four failed CI test shards share two obsolete test assumptions after the
lossless full-transcript C5 input change. Production code, validators, quotas,
provider approvals and prompt limits are unchanged in this leaf.

1. `ReportingBroker`, the synthetic database-test provider, copied compact C4
   input references directly into output findings. Those input references now
   contain `segment_id`, `quote_start` and `quote_end`; output evidence requires
   literal `quote`, `start_ms` and `end_ms`. The real worker correctly rejected
   the malformed fake report and recorded an uncertain task. The fake broker
   now derives the exact literal span from the complete source rows. All output
   still passes the production provider/report validators.
2. The older mixed-script tests compared C4 transport representation directly
   and expected facts-only input sizes. They now reconstruct every quote and
   timestamp from ranges and compare them with the original complete facts;
   they also assert every source row is retained in order. The 64-fact case
   requires the existing 48,000-unit allowance when full context is included.
   The original 152-turn, thirteen-repetitions-per-turn fixture is retained and
   tested for explicit rejection at every relevant output allocation, including
   the 8,000-output-token route. An additional 152-turn case with six repetitions
   verifies successful complete context within the existing 96,000-total-unit
   route, through a synthetic 1,000-paise approval and fake child. It does not
   reduce the original over-budget coverage or change a production limit.

## Receipts

- Before: the actual PostgreSQL pipeline `groq-False` case reproduced the CI
  uncertain-task failure in 24.21 seconds. Receipt:
  `D:/AC-authority-closers-release-audit/peer-ci-context-before-20260915.xml`.
- After: 14 PostgreSQL reporting, review and reviewer-access cases passed in
  127.10 seconds. Receipt:
  `D:/AC-authority-closers-release-audit/peer-ci-context-after-20260915.xml`.
- 56 mixed-script/context/budget unit cases passed in 3.51 seconds. Receipt:
  `D:/AC-authority-closers-release-audit/peer-ci-context-unit-final-20260915.xml`.
- Six additional PostgreSQL cases passed in 142.57 seconds: governed Gemini
  processing plans (two variants), composed runtime, authority/cache reuse,
  exact plan acceptance bindings, and guest HTTP upload-to-overview settlement.
  Receipt: `D:/AC-authority-closers-release-audit/peer-ci-context-runtime-20260915.xml`.
- Ruff lint/format and `git diff --check` passed for both changed test files.

Database tests used isolated schemas on disposable loopback PostgreSQL and the
existing source/hash-verified native AudioAtlas binary. No real recording,
external provider, production database, browser profile or deployment was used.
The CI rerun and production recovery remain release-owner work.
