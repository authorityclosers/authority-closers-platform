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
