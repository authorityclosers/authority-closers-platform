"""Offline merged-source verification; never install to the real host."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "infra/watchdog/ac_usage_guard.py"
INSTALLER = "infra/watchdog/install-usage-guard.sh"
GIT = shutil.which("git")
BASH = shutil.which("bash")
assert GIT is not None and BASH is not None


def git(repo, *args):
    result = subprocess.run(  # noqa: S603 - private fictional repository, fixed git argv
        [GIT, "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def commit(repo, *, merged=True):
    git(repo, "add", "infra/watchdog")
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-m", "Fictional source")
    revision = git(repo, "rev-parse", "HEAD")
    if merged:
        git(repo, "update-ref", "refs/remotes/origin/main", revision)
    return revision


@pytest.fixture
def offline_repo(tmp_path):
    repo = tmp_path / "fictional-repo"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    git(repo, "config", "user.name", "Fictional guard operator")
    git(repo, "config", "user.email", "fictional@example.invalid")
    for path in (SOURCE, INSTALLER):
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
        target.chmod(0o755)
    revision = commit(repo)
    tools = tmp_path / "tools"
    tools.mkdir()
    marker = tmp_path / "forbidden-dependency"
    # A dry-run or refusal must never reach any write, runtime or provider command.
    for name in (
        "sudo",
        "mktemp",
        "cp",
        "mv",
        "ln",
        "chmod",
        "chown",
        "install",
        "rm",
        "systemctl",
        "curl",
        "wget",
        "claude",
        "timeout",
    ):
        trap = tools / name
        trap.write_text(f"#!/bin/sh\nprintf attempted > {shlex.quote(str(marker))}\nexit 99\n")
        trap.chmod(0o755)
    env = {
        "PATH": f"{tools}:{os.environ['PATH']}",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    return repo, revision, env, marker


def snapshot(repo):
    return {
        str(path.relative_to(repo)): (
            path.read_bytes(),
            path.stat().st_mode,
            path.stat().st_mtime_ns,
        )
        for path in repo.rglob("*")
        if path.is_file()
    }


def run(offline_repo, *args, invocation=None):
    repo, _, env, marker = offline_repo
    before = snapshot(repo)
    result = subprocess.run(  # noqa: S603 - checked-in shell and private repo/write traps
        [BASH, str(invocation or repo / INSTALLER), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert snapshot(repo) == before
    assert not marker.exists()
    return result


def refused(offline_repo, *args, invocation=None):
    result = run(offline_repo, *args, invocation=invocation)
    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stderr.strip() == "Refused: unverified usage-guard source"
    assert "Verified source" not in result.stdout


def test_dry_run_is_default_repeatable_and_writes_nothing(offline_repo):
    repo, revision, _, _ = offline_repo
    digest = hashlib.sha256((repo / SOURCE).read_bytes()).hexdigest()
    for mode in ([], ["--dry-run"], ["--dry-run"]):
        result = run(offline_repo, *mode, "--source-revision", revision)
        assert result.returncode == 0, result.stderr
        assert f"Verified source revision: {revision}" in result.stdout
        assert f"Verified source SHA256: {digest}" in result.stdout
        assert "to /opt/ac-watchdog/ac_usage_guard.py; no host files changed" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--source-revision"],
        ["--source-revision", "main"],
        ["--source-revision", "a" * 7],
        ["--source-revision", "A" * 40],
        ["--source-revision", "0" * 40],
        ["--unknown"],
    ],
)
def test_refuses_invalid_arguments_or_unavailable_revision(offline_repo, args):
    refused(offline_repo, *args)


def test_refuses_duplicate_or_conflicting_options(offline_repo):
    _, revision, _, _ = offline_repo
    for args in (
        ["--dry-run", "--install", "--source-revision", revision],
        ["--source-revision", revision, "--source-revision", revision],
        ["--install", "--install", "--source-revision", revision],
    ):
        refused(offline_repo, *args)


@pytest.mark.parametrize("path", [SOURCE, INSTALLER])
def test_refuses_dirty_source_or_installer_before_install(offline_repo, path):
    repo, revision, _, _ = offline_repo
    with (repo / path).open("a") as altered:
        altered.write("\n# fictional unreviewed change\n")
    for mode in ("--dry-run", "--install"):
        refused(offline_repo, mode, "--source-revision", revision)


def test_refuses_unmerged_source(offline_repo):
    repo, _, _, _ = offline_repo
    with (repo / SOURCE).open("a") as altered:
        altered.write("\n# fictional unmerged change\n")
    revision = commit(repo, merged=False)
    refused(offline_repo, "--install", "--source-revision", revision)


def test_refuses_missing_main_evidence_or_noncommit(offline_repo):
    repo, revision, _, _ = offline_repo
    blob = git(repo, "rev-parse", f"HEAD:{SOURCE}")
    refused(offline_repo, "--source-revision", blob)
    git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    refused(offline_repo, "--source-revision", revision)


@pytest.mark.parametrize("symlink", [False, True])
def test_refuses_missing_or_symlink_source(offline_repo, tmp_path, symlink):
    repo, revision, _, _ = offline_repo
    source = repo / SOURCE
    source.unlink()
    if symlink:
        copy = tmp_path / "untracked-source.py"
        shutil.copyfile(ROOT / SOURCE, copy)
        source.symlink_to(copy)
    refused(offline_repo, "--source-revision", revision)


@pytest.mark.parametrize("kind", ["copy", "symlink"])
def test_refuses_relocated_or_symlink_installer(offline_repo, kind):
    repo, revision, _, _ = offline_repo
    invocation = repo / "infra/watchdog/untracked-installer.sh"
    if kind == "copy":
        shutil.copyfile(repo / INSTALLER, invocation)
    else:
        invocation.symlink_to(repo / INSTALLER)
    refused(offline_repo, "--source-revision", revision, invocation=invocation)


@pytest.mark.parametrize("path", [SOURCE, INSTALLER])
def test_refuses_nonexecutable_git_blob(offline_repo, path):
    repo, _, _, _ = offline_repo
    (repo / path).chmod(0o644)
    revision = commit(repo)
    refused(offline_repo, "--source-revision", revision)


@pytest.mark.parametrize("missing", ["binding", "alias", "nested", "refresh", "syntax"])
def test_refuses_merged_but_unfixed_source(offline_repo, missing):
    repo, _, _, _ = offline_repo
    path = repo / SOURCE
    source = path.read_text()
    replacements = {
        "binding": "# import subprocess",
        "alias": "import subprocess as wrong_binding",
        "nested": "def unrelated():\n    import subprocess",
    }
    if missing in replacements:
        source = source.replace("import subprocess", replacements[missing], 1)
    elif missing == "refresh":
        source = source.replace("def keep_token_fresh(", "def stale_token_fresh(", 1)
    else:
        source += "\ndef invalid(:\n"
    path.write_text(source)
    revision = commit(repo)
    for mode in ("--dry-run", "--install"):
        refused(offline_repo, mode, "--source-revision", revision)


@pytest.mark.skipif(os.geteuid() == 0, reason="non-Root refusal proof")
def test_install_requires_root_after_source_verification(offline_repo):
    _, revision, _, _ = offline_repo
    result = run(offline_repo, "--install", "--source-revision", revision)
    assert result.returncode == 1
    assert "Install requires Root under the separate SHA-specific install card" in result.stderr
