# D1 dashboard and weekly report — AUT-1099

Base: `1b0bd32048a9384242cd6eb28f9bc30a240b967c`. Reuses the deployed AUT-1022 normalizer (`6b5ff8295a5d2e0daba78a6a6a9dcd38632b208d`), AUT-1017's three-panel layout and AUT-1020 measurement revision `6b3cf8b5-c139-4b21-81e8-a6760312ec8d`. Historical documents are preserved.
`build_report` groups accepted tasks using explicit `Task type:` / `Tier:` card lines; missing/conflicting declarations stay unknown. `render_fictional_d1(report, view)` renders `dashboard` and `weekly-report` with identical panels/figures and fictional labels. Incomplete groups have no numeric baseline; reported subtotal excludes unknown runs. Independent Quality, rework runs and provider allowance stay unknown. No live receipt collection or new CLI/network path.

Repeatable local/dev replay (existing approved interpreter; scratch/cache only, no API calls):

```bash
TMPDIR="$PAPERCLIP_RUN_SCRATCH_DIR" PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/infra/test_agent_scorecard.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location('fixtures', 'tests/infra/test_agent_scorecard.py')
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
for source in (f.fixture_source(f.FIXTURE), f.session_source('codex_local'), f.session_source('claude_local')):
    report = f.report(source)
    dashboard = f.scorecard.render_fictional_d1(report)
    weekly = f.scorecard.render_fictional_d1(report, 'weekly-report')
    assert dashboard.split('\n', 1)[1] == weekly.split('\n', 1)[1]
    print(dashboard, weekly)
PY
```

Both views: Codex all-known `285.00`, legacy Claude all-known `445.00`, each 1 accepted/covered task (100%); per_run and session_delta remain independent. Incomplete week: 2 accepted, 1 covered, 1 unknown task, `2 runs unreported`, subtotal `418.00`; unknown group subtotal `268.00`, median/p90 `n/a (incomplete usage)`. Cycle median/p90 `5.50d`/`6.00d`, review returns `3`. No-run tasks remain uncovered. Usage includes all returned runs for accepted tasks, including out-of-week runs, as in the existing scorecard.

Local verification (all exit 0): focused pytest **103 passed in 0.80s**; fixture comparison above passed; `ruff format --check packages/python tests` (948 files); `ruff check packages/python tests scripts/agent_scorecard.py`; `mypy --cache-dir "$PAPERCLIP_RUN_SCRATCH_DIR/mypy-cache" packages/python` (396 source files); `ac-gate check`. Existing CLI success 0 / failure 2 and GET-only regressions pass. No normalizer semantics changed.
Issue documents `dashboard` and `weekly-report` carry the same commit and fixture SHA-256 pins. After merge, the release operator must verify dev source contains the merge and run this replay with the approved interpreter, then verify staging readiness/source through the established release path. Local evidence does not claim deployment or CI completion; those receipts belong on the task.
