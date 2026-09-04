# Phase-1 intelligence harness implementation evidence

Date: 2026-09-04
Scope: inert, provider-neutral, pure-Python contract foundation only

## Authority and scope

This slice follows the controlled implementation and governance references in
`docs/traceability/CONTROLLED_SOURCE_REGISTER.md`. It does not activate AI data
processing, retrieval, embeddings, scoring, simulation authority, real-call
processing, or a provider SDK.

The harness is advisory-only. It has no HTTP route, persistence path, database
write, tool registry, side effect, or canonical business-state authority.

## Changed files

- `packages/python/ac_platform/intelligence/contracts.py`
  - bounded tenant-scoped generation request
  - strict UUID, token-count, sequence-item and timezone validation
  - defensive tuple normalization for all sequence inputs
  - model profile and normalized generation result
  - typed `answer`, `abstain`, and `escalate` outcomes
  - citation and evidence bounds
  - request-evidence citation grounding helpers
  - execution provenance and output digest
  - provider-neutral `GenerationPort` protocol
- `packages/python/ac_platform/intelligence/errors.py`
  - validation, policy, deadline, provider, tool, and budget error taxonomy
- `packages/python/ac_platform/intelligence/orchestrator.py`
  - support-only admission, deadline enforcement including late cancellation
    suppression (including cancellation-ignoring providers), result
    identity/budget checks, citation grounding, and a fail-closed provider
    boundary
- `packages/python/ac_platform/intelligence/__init__.py`
  - explicit public exports
- `tests/unit/intelligence/test_harness.py`
  - focused contract, bounds, timeout, cancellation suppression/ignoring,
    identity, immutability, budget, citation, policy, mutation and outcome
    tests

## Deliberate non-goals

- No provider SDKs or model downloads.
- No model execution, HTTP surface, retrieval or vector store.
- No embeddings, reranking, scoring, simulation transitions or official
  evaluation.
- No tools or write-capable actions.
- No changes to UI, TypeScript, bridge files, migrations, deployment, settings,
  VPS, secrets, or database state.

## Verification record

Commands run from the requested persistent worktree:

```text
.\.venv\Scripts\ruff.exe format --check packages/python/ac_platform/intelligence tests/unit/intelligence
5 files already formatted

.\.venv\Scripts\ruff.exe check packages/python/ac_platform/intelligence tests/unit/intelligence
All checks passed!

.\.venv\Scripts\mypy.exe packages/python/ac_platform
Success: no issues found in 127 source files

.\.venv\Scripts\pytest.exe -q tests/unit/intelligence
25 passed in 0.18s

uv run pytest -q tests/unit
879 passed, 1 Starlette/httpx deprecation warning in 21.77s
```

The full Python unit suite was rerun independently after the final deadline and
citation-grounding fixes. The single warning is an existing dependency
deprecation warning from `fastapi.testclient`; it is not introduced by this
slice.

`git status --short` shows the concurrent learner UI changes plus the new files
listed above; no existing bridge, settings, migration, deployment, or database
files were changed by this slice.
