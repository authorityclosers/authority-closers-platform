# AUT-576: canary retention refusal

Lane: devenv. Tier: routine. Base: `c76cdf428490a38ff695b871657f649055a28b6b`.
Authority: [CTO option A decision](/AUT/issues/AUT-576#comment-85992592-4517-4496-a640-13343521b58b).

Staging's approved keep-for-training policy caused the canary to exit before
printing a result. The train wrapper consequently reported `canary_no_result`.
The canary now accepts keep-for-training retention in development and staging.
Production continues to require standard retention of seven days or fewer,
without a keep-for-training reference. Other policies over seven days are
refused in every environment.

A retention refusal prints JSON with `ok: false`,
`stage_reached: "refused"`, `failure_code: "canary_refused_retention"` and
`retention_ref`, then exits 1 before opening a database or submitting audio.
Every emitted result includes `retention_ref`; disabled analysis uses null.
Missing runtime/configuration retains the generic exit-2 refusal.

## Local verification

Run in the claimed lane checkout with Python 3.12.3:

```sh
PYTHONPATH=packages/python .venv/bin/python -m pytest \
  tests/unit/conversation_intelligence/test_canary_cli.py \
  tests/unit/conversation_intelligence/test_canary_fixture.py \
  tests/infra/test_canary_timer.py
PYTHONPATH=packages/python .venv/bin/python -m ruff check \
  packages/python/ac_platform/conversation_intelligence/canary_cli.py \
  tests/unit/conversation_intelligence/test_canary_cli.py \
  tests/infra/test_canary_timer.py
PYTHONPATH=packages/python .venv/bin/python -m ruff format --check \
  packages/python/ac_platform/conversation_intelligence/canary_cli.py \
  tests/unit/conversation_intelligence/test_canary_cli.py \
  tests/infra/test_canary_timer.py
PYTHONPATH=packages/python .venv/bin/python -m mypy \
  packages/python/ac_platform/conversation_intelligence/canary_cli.py
git diff --check
```

Results: 41 tests pass (25 CLI, one fixture, 15 wrapper/timer); Ruff and mypy
pass. Ten retention cases cover standard and keep-for-training policies across
all three environments. Allowed cases prove the pipeline reaches engine
creation using a mock; refused cases prove no database is opened. Scripted
pipeline tests cover report validation, failures, timeout and the quote cap.
The wrapper regression preserves the retention reference in history, exits
non-zero, and emits exactly one alert with the specific refusal reason.

The existing dev API returns HTTP 200, alive/ready, at both health routes on
port 8100 with the dev Host. Its release is `local-unreleased`, so this is
baseline health evidence, not deployed proof of the candidate.

## Deployed acceptance still required

After CTO review, CEO merge approval and automatic staging deployment, check
that dev refresh serves a commit containing this fix. Then verify one staging
canary result: `ok: true`, `stage_reached: "C6"`, `report_present: true`, the
approved retention reference and recorded stage durations. Use the installed
timer or a Root & Infra task to run the existing staging unit. Keep
[AUT-576](/AUT/issues/AUT-576) open until that proof is recorded.

The local tests use mocks and the fictional fixture; no provider call or
environment setting/data change was performed. The future training-export
exclusion requirement is tracked separately in [AUT-581](/AUT/issues/AUT-581).
