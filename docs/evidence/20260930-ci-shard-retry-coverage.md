# AUT-616: same-SHA shard retry coverage

2026-10-01; fictional fixtures in the platform lane's dev environment.
Base: `4c54f9a5e5c8b050536e9f8dc5f6bccfaef093f7`.
Implementation revision: `64dd947e45adc444501267e3245aae1ea895285b`.
Scope exception recorded on the issue under Unjam rule 1: update the stale download-pattern assertion in `tests/infra/test_recovery_ci_gates.py`.

Artifact uploads retain attempts. Downloads retain separate directories across same-SHA attempts. All directory names are validated before selecting the highest attempt per index; selected manifests must match their directory index. Existing coverage checks and `PYTHON_TESTS_RESULT` success gating remain in place; no manifest schema change.

Command results (exit 0 unless specified):
- `python3 scripts/ac_task.py start platform 616-shard-retry-coverage`: started from latest main.
- `python3 scripts/ac_task.py check`: task may be worked on.
- `uv run pytest tests/unit/ci/test_python_test_shard.py -q`: 29 passed.
- `uv run pytest tests/unit/ci/test_python_test_shard.py tests/infra/test_recovery_ci_gates.py -q`: 38 passed.
- Changed-file `uv run ruff format --check` and `uv run ruff check`: passed for both changed test files and the verifier.
- `uv run mypy scripts/ci/python_test_shard.py`: no issues in 1 source file.
- `pnpm run format:check`: passed; 795 Python files formatted.
- `pnpm run typecheck`: passed; Python mypy checked 334 source files.
- `pnpm run lint`: passed; frontend ESLint and Python Ruff.

Dev reproduction (use a fresh fixture directory; all generated data is fictional):
```bash
uv run python - <<'PY'
import os, runpy, subprocess, sys
from pathlib import Path
root = Path(os.environ['PAPERCLIP_RUN_SCRATCH_DIR']) / 'retry-repro'
root.mkdir()
h = runpy.run_path('tests/unit/ci/test_python_test_shard.py')
exclusions = h['retry_fixture'].__wrapped__(root)
cmd = [sys.executable, 'scripts/ci/python_test_shard.py', 'verify', '--root', str(root), '--manifest-dir', str(root/'manifests'), '--exclude-file', str(exclusions), '--shard-count', '4', '--sha', h['SHA'], '--run-attempt', '2']
assert subprocess.run(cmd).returncode == 0
missing = h['_artifact'](root, 1)
missing.unlink(); missing.parent.rmdir()
assert subprocess.run(cmd).returncode == 2
PY
```
Observed mixed-attempt stdout (exit 0):
```text
selected shard 0: attempt 1
selected shard 1: attempt 1
selected shard 2: attempt 2
selected shard 3: attempt 1
```
Missing index: exit 2; stderr starts `python test shard configuration error: expected 4 shard manifests, found 3 in ` followed by the fixture manifest directory.
Required CI, CTO review, CEO approval and merged-revision verification on dev remain before completion. After merge record the dev revision and rerun the focused tests and this fixture; browser QA is unnecessary.
