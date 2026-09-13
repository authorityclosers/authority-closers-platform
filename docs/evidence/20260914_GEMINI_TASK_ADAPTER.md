# Gemini task adapter implementation evidence

Worktree: `D:/Projects/authority-closers-xray-gemini-engine`.
Base is the frozen overview `4bac49c` plus the funded-source packet `9bbead1`.
This packet owns task envelopes, result validation, provider propagation and
router compatibility. It changes no migrations, human authorization policy,
credential material, infrastructure, DNS or deployment state.

## Verified here

- Final complete conversation unit suite: 623 passed, one Windows/POSIX ownership
  skip. This includes native AudioAtlas checks and 30 focused native Gemini
  cases. Do not add those 30 again to the total.
- Seven actual disposable PostgreSQL cases passed in 83.69 seconds. Four cases
  exercise Groq/Gemini single and multiple C4 chunks, private reports, replay,
  deletion and switching the judge while retaining identical C0–C4 checkpoints.
  Two drive current server-approved free/funded Gemini C4/C5 through the fixed
  router, durable scheduler and worker to the private structured report. One
  rejects the whole plan when individually fitting stages exceed the project
  cap in total. All provider
  responses are synthetic; the database and production pipeline are real.
- UI suite: 91 passes, including exact funded upper-limit display, explicit
  consent and rejection of a false zero-cost label. Static export build,
  TypeScript and scoped ESLint pass.
- Real Chromium/HTTP test: one pass in 48.01 seconds. The compiled app reads a
  durable synthetic Gemini C4/C5 report through actual cookie auth, PostgreSQL
  and AC HTTP routes, verifies the mounted overview, replays private source
  audio and performs local upload. No API route mock; provider responses are
  deliberately synthetic. Receipt lists observed network paths and checks.
- Ruff passes for all 15 changed Python files; all are formatted. Mypy passes
  for eight changed source files, with the six affected source files rechecked
  after adding complete-plan pricing. `git diff --check` passes.
- The existing native binary was reused only after matching its binary SHA-256
  to the build manifest; the native tests validate the checked-in source binding.
  Binary and manifest are ignored build artifacts, not committed executables.

Portable JUnit receipts and hashes are in `gemini-task-adapter-20260914/` beside
this file. Tests use external private-storage roots and a disposable loopback
PostgreSQL database. Its existing bootstrap credential is resolved in process
memory; no credential values/DSN are in the receipts.

## Failures preserved

The first router tests parsed a JSON-mode dump with the strict Python-mode
Pydantic entry point; two fixture cases failed. Using the JSON parser fixed them
without relaxing UUID/tuple validation. The first PostgreSQL attempt passed two
cases and failed three test assertions: the intentional alternate-model test
selected an unimplemented model (correctly rejected before the later quote
check), and the report lookup used `id` instead of the task's `run_id`. The
alternate-model assertion now selects a supported different model and verifies
that its original quote still rejects it. The five-case rerun passed, followed
by seven passing cases after adding the complete-plan cost checks.

Earlier receipts remain outside the repo under
`D:/AC-authority-closers-release-audit/gemini-*-20260914*`; no failed receipt is
relabeled as a success. No application repair was required after these fixture
failures.

## Not proved by this packet

No new provider call, real-call benchmark, hosted worker activation,
staging deployment or production deployment occurred here. The release coordinator owns
combined CI/images, the explicit guest processing principal/ownership seam,
hosted activation and authenticated canary/rollback proof. Gemini's earlier
tiny connectivity smoke belongs to that lane and is not a full-report result.
