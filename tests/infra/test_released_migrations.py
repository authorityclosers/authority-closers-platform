"""Released migrations are history (v0.86 root cause 3): the wb-ci check on real git repos."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "released_migrations", ROOT / "scripts/ci/released_migrations.py"
)
assert SPEC and SPEC.loader
released = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = released
SPEC.loader.exec_module(released)

VERSIONS = "db/migrations/versions"


FIXTURE_GIT = ("git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid")


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed git argv in a temporary repository
        [*FIXTURE_GIT, *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def write(repo: Path, name: str, text: str) -> None:
    path = repo / VERSIONS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    git(tmp_path, "init", "--quiet", "--initial-branch=main")
    git(tmp_path, "config", "core.autocrlf", "false")
    write(tmp_path, "20261018_0096_partner_webhooks.py", '"""Released."""\nrevision = "0096"\n')
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "--quiet", "-m", "release")
    git(tmp_path, "checkout", "--quiet", "-b", "workbench")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def commit(repo: Path, message: str) -> None:
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "-m", message)


def test_unchanged_history_and_new_revisions_pass(repo: Path, capsys) -> None:
    write(repo, "20261024_0128_new.py", 'revision = "0128"\n')
    commit(repo, "new revision")
    assert released.main(["--base", "main"]) == 0
    assert "PASS (1 released migrations unchanged on main)" in capsys.readouterr().out


@pytest.mark.parametrize("change", ["docstring", "mode", "delete", "rename"])
def test_any_change_to_a_released_migration_fails_with_the_rule(
    repo: Path, capsys, change: str
) -> None:
    path = repo / VERSIONS / "20261018_0096_partner_webhooks.py"
    if change == "docstring":
        path.write_text('"""Reworded."""\nrevision = "0096"\n', encoding="utf-8")
    elif change == "mode":
        path.chmod(0o755)
    elif change == "delete":
        path.unlink()
    else:
        path.rename(path.with_name("20261018_0096_renamed.py"))
    commit(repo, change)
    assert released.main(["--base", "main"]) == 1
    out = capsys.readouterr().out
    assert "released migrations are history; add a new revision" in out
    assert "20261018_0096_partner_webhooks.py" in out


def test_a_release_not_merged_back_yet_is_a_note(repo: Path, capsys) -> None:
    git(repo, "checkout", "--quiet", "main")
    write(repo, "20261024_0128_released_later.py", 'revision = "0128"\n')
    commit(repo, "a later release")
    git(repo, "checkout", "--quiet", "workbench")
    assert released.main(["--base", "main"]) == 0
    out = capsys.readouterr().out
    assert "note: db/migrations/versions/20261024_0128_released_later.py" in out


def test_an_unknown_base_cannot_pass(repo: Path, capsys) -> None:
    assert released.main(["--base", "origin/missing"]) == 2
    assert "fetch it first" in capsys.readouterr().out
