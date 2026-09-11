# Free-course continuation-selector evidence

Date: 2026-09-10

Scope: one isolated learner regression test for the transition from an existing free-course enrollment to the first server-authorized activity. No implementation, access, identity, media, production data, or browser state was changed.

Baseline qualification:

- Test worktree commit: `ec0009ec0ea0333d7cfa266d2c353d07ddaf1268`.
- Latest inspected implementation commit: `7bdd069d4bf00561edcab90b1679666205708185`, plus unrelated uncommitted work that was inspected read-only.
- The tested `firstActionableActivity` implementation has identical SHA-256 `16F2976B05A00DD4F10F8795935B098208586CEE215A38F2AEE22D27B51D405B` in both worktrees.

Source-baseline requirements for integration:

- `firstActionableActivity` remains an exported, pure selector over the server-projected `LearningResponse`.
- Selection remains constrained to activities with a non-empty server-provided `allowed_actions` list and published module/activity order; the client must not synthesize authority from position alone.
- If the helper or learner response contract changes from the inspected baseline, rerun this test against the final integrated source rather than relying on the recorded hash.
- The test is intentionally disjoint from sign-in return-path, media playback, username, and leaderboard feature code. Those areas need their own acceptance cases once stable public contracts exist.

Evidence:

- `pnpm --filter @ac/learner-web exec vitest run app/lib/revenue-journey-resume.acceptance.test.ts` — 1 file passed, 3 tests passed.
- `pnpm --filter @ac/learner-web exec tsc --noEmit` — passed.
- `pnpm --filter @ac/learner-web exec eslint app/lib/revenue-journey-resume.acceptance.test.ts --max-warnings 0` — passed.

The tests prove only that the learner home selector returns the first activity whose server-projected state is `in_progress` or `available` and whose `allowed_actions` list is non-empty. They also prove that no lesson is invented for paths with no matching activity, including empty and entirely locked paths. They do not prove the latest full journey, deployment, enrollment policy, identity, media, username, leaderboard, email delivery, or production behavior.

Readiness gaps observed without adding failing tests:

- Public free-course sign-in and registration links do not carry the originating course path, and the Google sign-in start URL currently returns to `/home`. A safe validated return-path contract is required before a passing journey acceptance test can be added.
- Current native playback evidence covers explicitly technical film fixtures, not published Dipak instruction. The latest upload pipeline evidence also says no prepared long film is attached or represented as Dipak instruction. An exact published/bound Dipak activity and reviewed server-owned watch-evidence policy are prerequisites for watch/seek/resume/progress acceptance.
- Persisted username claiming and opt-in canonical leaderboard work is owned by a separate implementation task. Acceptance must cover uniqueness, stale/duplicate claims, recovery, privacy/opt-in, tenant isolation, tie/finalization rules, and canonical-event replay without deriving rank or progress from analytics.
