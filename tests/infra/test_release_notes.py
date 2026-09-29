"""Tests for the shared first-parent release-notes reader."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/release/release_notes.py"
SPEC = importlib.util.spec_from_file_location("release_notes", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def git_command(*args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("git executable is not available")
    result = subprocess.run(  # noqa: S603 - fixture-only git argv; no shell is used.
        [executable, *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return git_command("-C", str(repo), *args)


def commit(repo: Path, filename: str, subject: str) -> str:
    (repo / filename).write_text(subject + "\n", encoding="utf-8")
    git(repo, "add", filename)
    git(repo, "commit", "--quiet", "-m", subject)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def tagged_history(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "fixture"
    repo.mkdir()
    git_command("init", "--quiet", "-b", "main", str(repo))
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    baseline = commit(repo, "base.txt", "Baseline")
    git(repo, "tag", "v0.2.0", baseline)
    commit(repo, "pr-94.txt", "Prepare release (#94)")
    git(repo, "checkout", "--quiet", "-b", "side")
    commit(repo, "side.txt", "Side branch change (#99)")
    git(repo, "checkout", "--quiet", "main")
    commit(repo, "pr-96.txt", "Fix release check (#96)")
    git(repo, "merge", "--quiet", "--no-ff", "--message", "Merge side branch", "side")
    tip = commit(repo, "pr-100.txt", "Update release docs (#100)")
    return repo, tip


def test_module_and_cli_return_first_parent_subjects_in_git_order(tagged_history) -> None:
    repo, tip = tagged_history
    expected = [
        "Update release docs (#100)",
        "Fix release check (#96)",
        "Prepare release (#94)",
    ]
    assert MODULE.release_notes(repo / ".git", "v0.2.0", tip) == expected
    result = subprocess.run(  # noqa: S603 - invokes this test's local CLI with argv; no shell.
        [
            sys.executable,
            str(SCRIPT),
            "--git-dir",
            str(repo / ".git"),
            "--from",
            "v0.2.0",
            "--to",
            tip,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == expected
    assert result.stderr == ""
