"""ac-bugs runs the issues module on its own inside the container (v0.93 production:
NoReferencedTableError for persons). In a fresh interpreter, after load_models(), every foreign
key of the issue tables resolves, and the host command runs the module through a bootstrap that
loads the models first."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

PROBE = """
from ac_platform.bug_reports import issues_cli
from ac_platform.bug_reports.models import BugIssue, BugIssueEvent, BugIssueReport
issues_cli.load_models()
for model in (BugIssue, BugIssueEvent, BugIssueReport):
    for key in model.__table__.foreign_keys:
        key.column
print("resolved")
"""


def test_the_module_resolves_its_foreign_keys_on_its_own() -> None:
    done = subprocess.run(  # noqa: S603 - a fixed probe in a fresh interpreter
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=False, cwd=ROOT
    )
    assert done.returncode == 0, done.stderr[-600:]
    assert done.stdout.strip() == "resolved"


def test_the_host_command_runs_the_module_through_the_bootstrap() -> None:
    source = (ROOT / "infra/application/scripts/ac-bugs").read_text(encoding="utf-8")
    assert "model_metadata()" in source and '"-c",\n            BOOTSTRAP,' in source
    assert '"-m",\n        MODULE,' not in source
