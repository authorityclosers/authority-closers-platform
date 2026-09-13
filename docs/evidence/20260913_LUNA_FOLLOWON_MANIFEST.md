# Luna follow-on release manifest — 2026-09-13

This manifest records the isolated follow-on built from release candidate
`41d3c5726a1b5d217259c034bf058d9107135b1f` (`41d3c57`). It is an integration
receipt, not a deployment or content-approval record.

## Integrated changes

- Auth recovery context: `c9bcb16`, `41d3c57`.
- India daily practice bank: `a348193`, with English, Hinglish and
  Marathi-English (Marlish) labels and three Pune/Mumbai/Nagpur scenarios per
  language. The three reviewed sets are published in
  `packages/python/ac_platform/practice/exercise-library.published.json`; the
  eight legacy sets remain visible in the baseline pilot catalog and retain
  their existing draft/deep-link behavior.
- Arcade legacy cursor compatibility: `b007a68` (source `c1fcfce`).
- Practice activation receipt validation: `e85c1de`.
- Canonical daily-selection policy is approved for the three new published sets and
  records the independent Luna review plus the Codex release coordinator's
  approval under user delegation; it remains formative-only and cannot grant
  course access.
- Academy-scoped opt-in discovery, profile projection, mutual connections,
  block/report and learner UI: `cd73213`, `f822087` (sources `a4564ee`,
  `317e898`).
- Migration graph reconciliation and model-registry coverage: `48d4539`.
  Community tables use `20260913_0033_community_connections` after the Sales
  Xray `20260913_0032` parent; no duplicate `0032` revision is introduced.
- Backup/restore parity now carries the Sales `0032` inventory through the
  community `0033` head under `ac-postgres-parity-v13`. The populated rehearsal
  seeds both Sales plan tables, proves their rows survive `0032 → 0033`, and
  requires all five new community tables to be empty.

## Practice content boundary

The Marlish copy received an independent Luna review and the reported wording
issues were corrected. The three new sets are explicitly published with
`review_status: approved`; the eight legacy sets retain their prior draft
markers and remain visible. The activation command validates the published
language catalog and approved
daily-selection policy, so no official score, reward, progress, certificate or
assessment authority changed.

## Verification

- Focused Python/community/security practice suite: **212 passed**.
- Learner web focused Vitest suite: **74 passed**.
- Learner web typecheck and focused ESLint: **passed**.
- Actual published practice bundle receipt preparation: **passed** and is
  idempotent; receipt writes remain database-free.
- Ruff and `git diff --check`: **passed**.
- Backup/restore parity and restore-drill controller suite: **699 passed**, two
  expected Docker/opt-in skips.
- Populated PostgreSQL `0032 → 0033` rehearsal: **1 passed**, five related
  cases deselected; the dedicated database was dropped and `ac_local_sandbox`
  remained intact.
- Disposable loopback PostgreSQL after the social migration: community
  integration plus model-registry coverage **17 passed**; the test database was
  dropped and `ac_local_sandbox` was preserved.

## Release boundary

This worktree has not been promoted to staging or production. The release
owner must combine the Sales `0032` parent, this community `0033` migration,
reviewed practice inputs and the remaining release gates before deployment.
