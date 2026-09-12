# Preserve password-reset tokens during effect replay

Date: 2026-09-13 (Asia/Kolkata). Source parent: `c9583c8`.

The reset form previously read and removed its URL fragment on each mount-effect
setup. React StrictMode replays that setup: the first read found the valid token,
the second read found the cleared fragment, and the second queued state update
replaced the token with null. A valid reset link therefore showed unavailable.

An instance-scoped ref now guards the one-time fragment read, following the
existing verification flow. Token removal still happens immediately, and the
token remains only in memory. Reset still requires explicit form submission,
matching new passwords and the canonical token-verifying API. This changes no
expiry, single-use, session-revocation or identity rule.

Receipts under
`D:/Projects/authority-closers-release-transfer/2026-09-11-recovery`:

- `password-reset-hydration-red`: the actual default reset page mounted in
  StrictMode failed to expose its valid-token form; normal and missing-token
  controls passed (one failure, two passes).
- `password-reset-hydration-green`: all 53 tests across four reset,
  registration, Google-continuity and API-client files passed. TypeScript,
  formatting and zero-warning scoped ESLint also passed.

The new mounted tests assert immediate fragment removal, no token in query or
DOM, no reset before submit, the expected token used exactly once on explicit
submit, successful continuation, and missing-token refusal. Independent Luna
xhigh review found no actionable P0-P3 defect in this two-file correction.

Live local browser acceptance follows as a separate exact-checkpoint receipt.
No external verification/reset email delivery or production claim is made here.
