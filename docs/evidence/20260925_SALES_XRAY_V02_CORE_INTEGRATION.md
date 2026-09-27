# Sales Xray v0.2 core integration checkpoint

Tested source: `1377e7877dd4c2170dc6d5ada8c8dd4148c04dfe`.

This checkpoint combines the existing UI/auth/avatar integration at
`b9031db471f6f0659adb5873cb9c3efc819536f0` with these preserved source histories:

- `d946d873b8e64f6e50ddef55a81a61882058db61`: use the approved report completion limit and accept explicitly reviewed linguistic field labels without permitting numeric scoring.
- `ae06445c4151dc1e842441ca1d832de1330ef8f9`: return bounded, attempt-bound provider failure observations without exposing raw responses or treating uncertain outcomes as success.
- `3dcdbadee8b2a392233ded6b2d06725fef8a6c86`: resolve the named tester stage-count scope from the verified recording owner, retaining budget, consent, source, supplemental-attempt and unknown-outcome gates.

## Verification

All tests below used synthetic provider responses. Database checks used a disposable
loopback PostgreSQL database and separate test schemas; no hosted state or credentials
were changed.

| Check | Result |
| --- | --- |
| Focused report, budget, provider, broker, activation and tester unit tests | 326 passed in 11.78 seconds |
| Ruff on conversation intelligence and new regression tests | Passed |
| mypy on conversation intelligence | Passed, 89 source files |
| Real PostgreSQL tester-scope, stage-supplement, source-count and completed C2/C4/C5 cache-reuse regressions | 6 passed in 110.22 seconds |

The PostgreSQL selection was:

```text
tests/database/test_named_provider_stage_tester_postgresql.py
tests/database/test_stage_supplement_postgresql.py
tests/database/test_conversation_authority_postgresql.py::test_named_provider_request_scope_keeps_budget_and_uncertain_stage_holds
tests/database/test_conversation_authority_postgresql.py::test_authority_stage_max_requests_spans_same_source_on_second_recording
tests/database/test_conversation_authority_postgresql.py::test_authority_runs_c2_c4_c5_and_reuses_cached_effect
```

The first database attempt failed during local audio preprocessing because the new
checkout had no AudioAtlas binary. Direct reproduction returned
`signal_native_build_required`. After inspecting the native source and build path,
the existing verified `build_native()` function built the pinned source (SHA-256
`40b8b05256986da5eb5d49c3b3cb48c52d511117ecf2e59d56849457cb12fae3`).
A one-second synthetic WAV passed native inspection, then all six database tests
passed. No product code or assertions were changed to accommodate this setup failure.

Immutable local JUnit receipt hashes:

| Receipt | SHA-256 |
| --- | --- |
| Unit pass | `b9ec18de7b3af8fb2350ec60b9fb87935c97380ac40e26157e9c2e1e088b268f` |
| Initial database setup failure (retained) | `b1f70808d16655f75885b68a3aa90a99cf74710fd2483f62c6155f3bfb6672c4` |
| Database pass after verified native build | `b5057f93d64c30b3ce4427a2ccfd9a6b8126c422d84f855f8f3c5a677f22f50f` |

## Limits and next gates

This is an integration checkpoint, not a production acceptance receipt. Exact-head
CI, compiled browser acceptance, image packaging, staging and production verification
remain required. The inherited UI integration has earlier evidence; that evidence
does not establish the new Lightbox design or this combined release in production.

The first PR CI run (`36050342019`) exposed a formatting failure in the inherited
email-login regression file. Applying the pinned formatter changed no Python AST.
The full local Ruff lint and format checks then passed (713 files formatted).
The failed CI receipt is retained; a new exact-source run is required for the fix.

Provider failure observations do not yet implement durable retry coordination or
settlement. A post-dispatch unknown outcome must still prevent a repeat paid effect.
OpenAI C5 runtime integration and a real, matched report comparison are separate
pending work. No new provider report or Brain 3.0 semantic-quality result was generated
by these tests, and no Brain 3.1/3.2 source coverage is claimed.

## Groq allocation regression found by combined CI

Application run `36050628475` on `daa2d1bb4a9237cf7740ccf087c1ee8966973e95`
passed static, frontend, compiled acquisition browser, and gates checks. Two
Python shards failed because the new full-output allocation consumed space needed
by source evidence in the legacy Groq 8,000-token combined envelope. Local
reproduction confirmed `report_prompt_budget_exceeded` and a held processing plan.

The fix preserves Groq's existing 3,200-token C5 and 1,400-token C4 allocations,
bounded by the approved maximum. Explicit Gemini and OpenAI routes retain their
separately validated approved output caps. No approval, cost ceiling, input gate,
or test assertion was relaxed to make a failing report complete.

Validation on the corrected working tree:

- 133 focused report/allocation/Gemini unit tests passed in 3.07 seconds.
- All 20 PostgreSQL processing-plan tests passed in 241.28 seconds, including
  retained C2 reuse, exact stage bindings, exhausted audio-minute balance, and
  bounded invalid-response repair.
- The composed runtime and hosted-authority browser tests passed (2 tests,
  57.53 seconds).
- The durable processing-plan browser test passed in 33.75 seconds and checked
  that provider requests were not duplicated.
- Ruff lint, format and Git whitespace checks passed.

All provider responses in these tests were synthetic. Earlier failing CI/local
receipts remain preserved; this does not establish a hosted provider-quality result.

| Receipt | SHA-256 |
| --- | --- |
| Allocation units | `df984b038959d056cdabf105d322a81ab29f1156915969fa37a19a423e88692a` |
| Runtime and authority browser | `5d79079651279608108e5e77d9d6b425773032098ac2faf5bb0fe7f70e23e794` |
| Durable processing-plan browser | `3e264a07d7846780048b28039fc5e87ec36913ff377d3a7bafc3364cc5dc34aa` |
| Full PostgreSQL processing-plan module | `ad2868a5bd989e0cb25e50d959e4347efa4747da9620ef0fb500d34fc9523dab` |

## OpenAI C5 integration checkpoint

The combined tree includes the bounded Responses adapter at `0b159fb4` and
canonical C5 wiring at `5268108354d373d1d7014d19a002b82a2616a0c6`.
The worker service/router admit OpenAI for C5 only. The owner-authenticated C5
quote path now binds the selected prompt, language, qualitative pack, detailed
profile and approved cap while retaining the exact saved transcript/fact IDs.
OpenAI remains a single-attempt route; neither a malformed response nor a
transport ambiguity authorizes an automatic second paid request.

Import conflicts were resolved by retaining both OpenAI and the existing bounded
provider-failure observations, including their reservation binding. Combined
tests found and corrected an unintended change to Gemini's existing immutable
pricing-snapshot shape and display basis. Missing OpenAI usage remains unknown.
Explicit type narrowing fixed 17 static errors without relaxing runtime checks.

The report module's reviewed OpenAI change is limited to its docstring and prompt
provider admission. AST comparison against `ae06cb69` shows its other 52 functions
and classes unchanged. Report validation/adaptation remains revision 5; its full
source hash was repinned to `7bc877f94353babc42801f1436b43857d0ff89b8f774dbbac58258d96bd3231f`.

The combined unit suite passed 1,348 tests in 33.05 seconds. One POSIX-ownership
test is skipped on Windows. Ruff lint/format and mypy across 91 affected source
files passed. The first failing combined suite is preserved alongside the pass.
Real PostgreSQL OpenAI HTTP acceptance, independent semantic review, exact-source
hosted CI and canonical activation remain pending. No live OpenAI report or
production configuration change is established by this checkpoint.

## Returned-model verification and Admin compatibility

Independent review found that OpenAI's response model was not compared with the
approved model. The decoder now requires an exact supported-model match. The
worker first preserves the raw provider response and a receipt containing the
requested model, reported model and verification result. A mismatch is held for
review without automatic redispatch. Its usage stays visible, but no verified
cost estimate is shown.

Admin now accepts the reviewed OpenAI cache/context-tier pricing snapshot and its
dated source evidence. Existing provider snapshots still require their release
evidence, unknown fields remain rejected, and unsettled charges remain explicitly
unsettled. An unavailable model estimate uses the existing `usage_unavailable`
state, preventing an additive provider receipt from breaking the recordings page.

Validation:

- 73 focused OpenAI/worker/Admin unit tests passed; after the final compatible
  Admin-state mapping, all 19 Admin unit tests passed again.
- Both existing Gemini hosted-authority and durable-plan browser journeys passed
  with the integrated OpenAI/model-verification changes (66.56 seconds).
- The new canonical authenticated OpenAI HTTP/worker PostgreSQL test passed on
  the combined tree (27.36 seconds). It checks exact saved C2/C4 reuse, one C5
  provider request, settings-drift denial without new tasks/jobs/reservations,
  wrong-source and wrong-owner denial, saved report/checkpoint/receipt history,
  and uncertain cost reservations pending settlement evidence.
- Eleven Admin API/component tests and the Admin TypeScript check passed under
  the repository's pinned Node 24 runtime. Tests include OpenAI pricing parsing,
  unavailable estimates, strict legacy evidence and retained recordings.

Two initial root PostgreSQL attempts did not execute product behavior: the first
omitted the harness's named database environment variable; the second used a
missing scratch parent. Both receipts are preserved. Setting the documented
loopback variable and creating the dedicated external scratch directory allowed
the test to run. No production database, provider or customer clip was used.

The independent review's model-binding finding is addressed; hosted activation
and a real matched provider-quality comparison remain required. Synthetic test
success is not evidence of a live Brain-quality improvement.

The HTTP/worker database test now also injects a returned model different from
the quoted Luna model. It proves the task becomes uncertain, the job is held in
dead letter with the typed model-mismatch reason, raw response bytes and the
unverified receipt remain readable, no report/checkpoint is accepted, budget
reservation remains uncertain, C2/C4 checkpoints are unchanged, and another
worker pass causes no provider redispatch. This case passed in 19.68 seconds;
the matching-model case passed in the preceding parameterized run. The first
mismatch assertion omitted the standard `conversation_` error prefix; correcting
that test expectation required no product change. Its failed receipt is retained.

## Optional hosted OpenAI identity

The integration includes leaf `802584af7d3517b7649df9688a4ba0347cf93bb2`.
Existing hosted activations keep their four-provider overlay. An OpenAI worker
entry requires the separate source-owned overlay and dedicated identity leaf.
The installer clears inherited optional identity environment before Compose.
Runtime checks inspect directory and token metadata without reading token
contents, reject symlinks and unsafe ownership/modes, and prevent mounting a
broader secrets directory. The source archive includes both overlays.

The leaf's four focused suites passed 195 tests, with 23 platform-specific skips
on Windows. On the combined source at `6de26075`, the hosted lifecycle and native
activation preparer suites passed 42 tests with 18 POSIX-specific skips. Ruff,
whitespace and the changed Admin files' Prettier checks passed. Linux CI must
exercise the POSIX cases before release. No hosted credential activation or paid
provider generation is established by these local checks.

## Exact-source CI fixture correction

The first combined Linux CI run passed the frontend, compiled acquisition
browser journey, static checks, migration/role gates and three Python shards.
The fourth shard rejected one synthetic OpenAI response because its old fixture
omitted the returned model. Local reproduction confirmed the same failure.
The fixture now reports its literal Luna model; runtime validation is unchanged.
All 1,359 conversation unit tests then passed, with one POSIX ownership skip on
Windows (39.88 seconds). An intermediate local run used a temporary directory
under a repository ancestor and failed the storage boundary checks; its evidence
is retained. The passing run used the dedicated external scratch root.

Fresh exact-source CI is required after this test-only correction. The native
image built but its upload was refused by the repository artifact-pool ceiling;
retention review must preserve release and rollback evidence before retrying.
