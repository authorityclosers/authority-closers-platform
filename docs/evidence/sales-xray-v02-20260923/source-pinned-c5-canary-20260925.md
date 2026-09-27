# Human C5 canary configuration isolation

Date: 2026-09-25. Implementation: `dfeb2333d22c06cf190ba9a061d474a84d24ef38`, based on `bee5e3c8ede433e75d3f1df4b1aed59fe8290ccf`.

## Problem and resulting behavior

A human/source-specific C5 approval could name a saved OpenAI configuration while ordinary uploads remained on the activated baseline. The human quote path discarded that approval's configuration digest, so using the saved alternative would otherwise require changing the global activation. That would also change the route for ordinary processing actors.

The quote route now derives the configuration digest from the uniquely matching server-side tenant/person/source/stage approval. It passes that digest into the existing authority validation; the client cannot supply it. Zero or multiple matching approvals return 403. Processing actors cannot override their release-pinned configuration. No provider-activation mutation was added.

The persisted quote binds its selected configuration and retains existing current-approval, source, actor, route, expiry, acceptance and worker-dispatch checks. The canary reuses source-bound C2/C4 checkpoints and selects OpenAI only for the explicitly approved C5 request. The broader acquisition plan path is unchanged.

## Validation

The implementation owner ran the following against the exact five-file patch:

- 31 focused HTTP-selection and acquisition-provider-policy unit tests passed.
- Both parameterized OpenAI C5 HTTP/worker PostgreSQL variants passed using a disposable loopback PostgreSQL database and fake provider broker. They persist the saved alternative in the human quote while the baseline remains activated, then exercise dispatch and reporting. They also cover incorrect configuration and expired approval alongside existing actor/source/settings checks.
- The existing ProcessingActor acquisition-plan PostgreSQL regression passed.
- Ruff check and format, scoped mypy on the two changed source modules, and `git diff --check` passed.

The default temporary directory initially failed the private-storage fixture's Git-ancestor guard, before changed assertions executed. A dedicated non-repository private temporary directory and the worktree's native DSP test fixture were used for the successful database runs. This did not change storage protections or deployed state.

An independent read-only review of the exact commit found no blocker for the single-source Gemini-to-OpenAI C5 canary. Integration owner also read the complete diff, checked the release worktree was clean, and fast-forwarded this commit without conflicts. The review did not rerun the owner's tests.

## Limits and operational acceptance

These tests use synthetic fixtures and fake providers. They do not establish real OpenAI report quality, billing, staging deployment or production behavior. The real authorized one-request benchmark remains a separate acceptance step; no extra transcription, facts request, automatic retry or provider fallback is implied by this patch.

The integration test does not submit an additional ordinary ProcessingActor call after the canary. It does verify that activation/default configuration is unchanged, and the separate unit and PostgreSQL regression cover the unchanged processing path.

An adjacent pre-existing limitation remains: changing only configuration fields while retaining the same provider/model/prompt/input can reuse the old C5 checkpoint because its cache key does not contain the whole provider-configuration digest. The specified Gemini-to-OpenAI comparison changes provider/model and therefore does not collide. This patch does not introduce general multi-configuration selection or authorize repeated paid comparisons.

Release preparation must keep the global baseline active, provision only the exact source/person C5 approval, and pin the complete release source. A fresh release package, exact-source CI and real staging evidence are still required. Do not reuse an earlier activation package that switches the global configuration.
