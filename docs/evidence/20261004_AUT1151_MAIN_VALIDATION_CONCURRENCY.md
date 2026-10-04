# AUT-1151: active main application validation survives later merges

Source: latest main `d5af14fc105a1e3539e3e9ba7fc058fc10eb8c44`.
Started through `ac-gate start devenv 1151-main-validation` after the lane
reported FREE. Both `ac-gate check` and `python3 scripts/ac_task.py check`
passed. Source contains required PR #296 merge
`42bc0fd65d19d497e19003f6511fc7f4d7a36048` (`git merge-base --is-ancestor`
exited 0).

## Behavior

The previous `github.event_name != 'workflow_dispatch'` expression cancelled
active main-push Application validation whenever another main push arrived.
The workflow now cancels active runs only for `pull_request` events.
The existing workflow/ref/PR concurrency group stays intact.

| Incoming event | Cancels active run in its group | Result |
| --- | --- | --- |
| Main push | No | Active validation and packaging finish; newer main work waits |
| Updated PR | Yes | Superseded validation for that PR is cancelled |
| Manual dispatch | No | Existing non-cancelling behavior is preserved |

The retained limit permits one running and one pending run per group; newer
work may replace the pending run. This repair does not promise an artifact for
every intermediate main SHA. Push and dispatch on main share the same group;
distinct PR numbers have separate groups. These semantics follow
[GitHub's concurrency documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

## Local proof

The regression evaluates the workflow's actual cancellation expression for
push, PR and dispatch. Before the repair: **1 failed, 2 passed**, with the
main-push case returning true instead of false. After the repair:

```sh
uv run --frozen pytest tests/infra/test_application_release_guards.py tests/infra/test_recovery_ci_gates.py tests/infra/test_release_artifact_pool.py -q
uv run --frozen ruff check tests/infra/test_application_release_guards.py
uv run --frozen ruff format --check tests/infra/test_application_release_guards.py
pnpm exec prettier --check .github/workflows/application.yml
git diff --check
```

**48 tests passed**; lint, formatting and diff checks passed. A parsed YAML
comparison against source main confirmed the cancellation expression is the
only semantic workflow change: triggers, groups, validation dependencies,
packaging and artifact checks are identical. The existing packaging/admission
contract tests also passed. No host or environment configuration changed.

## Required post-merge handoff

This is source and local regression evidence. CTO review and CEO SHA-bound
approval are still required. After watchdog merge, use its CI event on this
issue to record a successful **main-push** Application validation run, its exact
main SHA, and the `ac-application` artifact ID and SHA-256 digest. Verify that
SHA contains `42bc0fd` and record whether later main pushes arrived during
the successful run. A PR run or manual dispatch is not the required output.

AUT-1149 consumes that verified descendant artifact through the unchanged
release engine and owns staging/dev recovery. No CI polling timer, runtime
deployment, hold change or artifact-admission exception is part of this repair.
