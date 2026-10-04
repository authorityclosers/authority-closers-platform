"""Root source receipts, fictional watchdog regressions and offline SHA installer."""

from __future__ import annotations

import ast
import builtins
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = "infra/watchdog/ac_watchdog.py"
INSTALLER_PATH = "infra/watchdog/install-watchdog.sh"
FIXTURE = json.loads((ROOT / "tests/infra/fixtures/ac_watchdog/c0.json").read_text())
SOURCE_RECEIPT = json.loads((ROOT / "tests/infra/fixtures/ac_watchdog/aut932.json").read_text())[
    "source"
]
STUDIO = FIXTURE["studio"]
GIT = shutil.which("git")
BASH = shutil.which("bash")
assert GIT is not None and BASH is not None
FEATURE_REVIEWERS = {
    "sx-report": "044cc30f-0a4d-4bcb-82e9-1e4e95148664",
    "sx-org": "134f6861-0d81-4c0e-8a81-d361703c31d5",
    "sx-billing": "10c721cf-7a41-4298-8e6f-342a1eda2a3b",
    "sx-shell": "f3bf11bf-694f-45a9-8318-d45a041a79d3",
    "sx-prospects": "3cd3a2e1-bd97-480f-92b5-bd9507913c67",
}


@pytest.fixture
def watchdog(monkeypatch):
    """Import actual source with no runtime files, network, DB or Telegram clients."""

    def forbidden(*args, **kwargs):
        raise AssertionError("Live watchdog client called")

    telegram = ModuleType("ac_telegram")
    telegram.COMPANY = "00000000-0000-0000-0000-000000000001"
    monkeypatch.setattr(
        telegram, "LINK", "https://fictional.example.invalid/issues/{}", raising=False
    )
    for name in ("paperclip", "send", "remember_message"):
        monkeypatch.setattr(telegram, name, forbidden, raising=False)
    postgres = ModuleType("psycopg")
    monkeypatch.setattr(postgres, "connect", forbidden, raising=False)
    monkeypatch.setitem(sys.modules, "ac_telegram", telegram)
    monkeypatch.setitem(sys.modules, "psycopg", postgres)
    monkeypatch.setattr(sys, "argv", ["ac_watchdog.py", "--dry-run"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(subprocess, "run", forbidden)
    spec = importlib.util.spec_from_file_location("c0_watchdog", ROOT / SOURCE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert not module.ACT
    yield module


def test_source_preserves_root_export_except_approved_scope_and_feature_lanes():
    source = (ROOT / SOURCE_PATH).read_bytes()
    # Keep AUT-850's historical receipt: undo only AUT-1050's constant additions.
    lanes = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign) and node.targets[0].id == "LANES"
    )
    source = source.replace(
        ast.get_source_segment(source.decode(), lanes).encode(),
        b'LANES = ("sales-xray", "platform", "admin", "ui", "devenv", "api", "billing")',
    )
    source = source.replace(b"|sx-report|sx-org|sx-billing|sx-shell|sx-prospects", b"")
    for lane, reviewer in FEATURE_REVIEWERS.items():
        source = source.replace(
            (
                f'                  "{lane}": '
                f'"/home/acdev/src/lanes/{lane}/authority-closers-platform",\n'
            ).encode(),
            b"",
        ).replace(f'    "{lane}": "{reviewer}",\n'.encode(), b"")
    for reviewer, name in (
        (FEATURE_REVIEWERS["sx-org"], "the Organisation Engineer"),
        (FEATURE_REVIEWERS["sx-billing"], "the Billing Engineer"),
    ):
        source = source.replace(f'    "{reviewer}": "{name}",\n'.encode(), b"")
    metadata = SOURCE_RECEIPT
    assert hashlib.sha256(source).hexdigest() == metadata["repository_sha256"]
    begin, end = b"# AUT-932 identity rule: begin", b"# AUT-932 identity rule: end\n"
    assert source.count(begin) == source.count(end) == 1
    aut850 = source[: source.index(begin)] + source[source.index(end) + len(end) :]
    guard = b"UI_GUARD_EXCLUDED.search(f)\n               or identity_path(f)]"
    assert aut850.count(guard) == 1
    aut850 = aut850.replace(guard, b"UI_GUARD_EXCLUDED.search(f)]")
    assert aut850.count(b" or identity_path(f)]") == 1
    aut850 = aut850.replace(b" or identity_path(f)]", b"]")
    assert hashlib.sha256(aut850).hexdigest() == metadata["aut850_sha256"]
    assert aut850.count(b"|scripts/ci/|scripts/data-changes/") == 1
    original = aut850.replace(b"|scripts/ci/|scripts/data-changes/", b"|scripts/data-changes/")
    assert hashlib.sha256(original).hexdigest() == metadata["original_sha256"]
    assert len(source.splitlines()) == metadata["lines"]
    assert metadata["redactions"] == metadata["config_injection"] == []
    assert STUDIO["old_lock"].encode() not in source
    assert b"/run/user/1002" not in source


@pytest.fixture
def studio_runtime(watchdog, tmp_path, monkeypatch):
    home = tmp_path / "fictional-home"
    state = home / ".local/state/ac-studio-sync/state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps(STUDIO["initial_state"]))
    lock_path = tmp_path / "shared-studio.lock"
    lock_path.touch()
    calls = []
    opened = []
    sleeps = []
    release_on_sleep = []
    original_open = builtins.open

    def mapped_open(file, *args, **kwargs):
        # Only the literal lock path is redirected; FREEZE itself is unchanged.
        if str(file).startswith("/run/"):
            opened.append(str(file))
            assert str(file) == STUDIO["lock"]
            file = lock_path
        return original_open(file, *args, **kwargs)

    def sleep(seconds):
        sleeps.append(seconds)
        if release_on_sleep:
            fcntl.flock(release_on_sleep.pop(), fcntl.LOCK_UN)

    def as_acdev(command, timeout):
        argv = shlex.split(command)
        calls.append((argv, timeout))
        assert argv == ["python3", "-c", watchdog.FREEZE, str(STUDIO["number"]), STUDIO["sha"]]
        assert timeout == 120
        with monkeypatch.context() as patch:
            patch.setattr(Path, "home", classmethod(lambda cls: home))
            patch.setattr(builtins, "open", mapped_open)
            patch.setattr(time, "sleep", sleep)
            patch.setattr(sys, "argv", ["-c", *argv[3:]])
            try:
                exec(compile(watchdog.FREEZE, "<unchanged-freeze>", "exec"), {})  # noqa: S102
            except SystemExit as exit_status:
                return SimpleNamespace(returncode=exit_status.code)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(watchdog, "as_acdev", as_acdev)
    return SimpleNamespace(
        home=home,
        state=state,
        lock=lock_path,
        calls=calls,
        opened=opened,
        sleeps=sleeps,
        release_on_sleep=release_on_sleep,
    )


def test_freeze_records_exact_head_using_current_lock(watchdog, studio_runtime):
    assert watchdog.freeze_studio_head(STUDIO["number"], STUDIO["sha"])
    expected = json.loads(json.dumps(STUDIO["initial_state"]))
    expected["approvals"][str(STUDIO["number"])] = STUDIO["sha"]
    assert json.loads(studio_runtime.state.read_text()) == expected
    assert studio_runtime.opened == [STUDIO["lock"]]
    assert studio_runtime.sleeps == []
    assert list(studio_runtime.state.parent.iterdir()) == [studio_runtime.state]


def test_held_shared_lock_refuses_freeze_without_overwriting_state(watchdog, studio_runtime):
    before = studio_runtime.state.read_bytes()
    with studio_runtime.lock.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_SH | fcntl.LOCK_NB)
        assert not watchdog.freeze_studio_head(STUDIO["number"], STUDIO["sha"])
    assert studio_runtime.state.read_bytes() == before
    assert studio_runtime.opened == [STUDIO["lock"]]
    assert studio_runtime.sleeps == [1] * 90
    assert list(studio_runtime.state.parent.iterdir()) == [studio_runtime.state]


def test_freeze_waits_for_shared_lock_release(watchdog, studio_runtime):
    with studio_runtime.lock.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_SH | fcntl.LOCK_NB)
        studio_runtime.release_on_sleep.append(holder)
        assert watchdog.freeze_studio_head(STUDIO["number"], STUDIO["sha"])
    assert studio_runtime.sleeps == [1]
    assert (
        json.loads(studio_runtime.state.read_text())["approvals"][str(STUDIO["number"])]
        == (STUDIO["sha"])
    )


def test_old_user_lock_does_not_block_current_freeze(watchdog, studio_runtime, tmp_path):
    # The old path is fictional too; holding it must have no effect on FREEZE.
    with (tmp_path / "old-user-1002.lock").open("a") as old_holder:
        fcntl.flock(old_holder, fcntl.LOCK_SH | fcntl.LOCK_NB)
        assert watchdog.freeze_studio_head(STUDIO["number"], STUDIO["sha"])
    assert studio_runtime.opened == [STUDIO["lock"]]
    assert studio_runtime.sleeps == []


def test_absent_studio_state_is_existing_noop(watchdog, studio_runtime):
    studio_runtime.state.unlink()
    studio_runtime.state.parent.rmdir()
    assert watchdog.freeze_studio_head(STUDIO["number"], STUDIO["sha"])
    assert studio_runtime.opened == []
    assert not studio_runtime.state.parent.exists()


@pytest.mark.parametrize(
    ("freeze_ok", "held", "main", "checks", "expected_freezes", "expected_merges"),
    [
        (False, False, "green", "success", 1, 0),
        (True, False, "green", "success", 1, 1),
        (True, True, "green", "success", 0, 0),
        (True, False, "red", "success", 0, 0),
        (True, False, None, "success", 0, 0),
        (True, False, "green", "failure", 0, 0),
    ],
)
def test_studio_merge_preserves_freeze_hold_main_and_check_guards(
    watchdog, monkeypatch, freeze_ok, held, main, checks, expected_freezes, expected_merges
):
    number, sha = STUDIO["number"], STUDIO["sha"]
    branch = watchdog.STUDIO_BRANCH + "fictional"
    freezes, merges, notes = [], [], []

    def github(path):
        if path == "/pulls?state=open&per_page=20":
            return [{"number": number, "head": {"sha": sha, "ref": branch}}]
        assert path == f"/commits/{sha}/check-runs?per_page=100"
        return {"check_runs": [{"status": "completed", "conclusion": checks}]}

    def freeze(*args):
        freezes.append(args)
        return freeze_ok

    def merge(*args):
        merges.append(args)
        return True, ""

    conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: ("AUT-FAKE",)))
    monkeypatch.setattr(watchdog, "ACT", True)
    monkeypatch.setattr(watchdog, "gh_api", github)
    monkeypatch.setattr(
        watchdog, "pr_approvals", lambda *args: ("fake-task", "fake-cto", "fake-ceo", None, None)
    )
    monkeypatch.setattr(watchdog, "merge_held", lambda *args: held)
    monkeypatch.setattr(watchdog, "freeze_studio_head", freeze)
    monkeypatch.setattr(watchdog, "merge", merge)
    monkeypatch.setattr(watchdog.tg, "paperclip", lambda *args: notes.append(args))
    watchdog.pull_requests(conn, {"sent": {}}, {}, [], main=main)
    assert freezes == [(number, sha)] * expected_freezes
    assert merges == [(number, sha, branch)] * expected_merges
    assert len(notes) == expected_merges


def git(repo, *args):
    result = subprocess.run(  # noqa: S603 - private fictional repository, fixed git argv
        [GIT, "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def installer_repo(tmp_path):
    repo = tmp_path / "fictional-repo"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    git(repo, "config", "user.name", "Fictional C0 operator")
    git(repo, "config", "user.email", "fictional@example.invalid")
    for path in (SOURCE_PATH, INSTALLER_PATH):
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
        target.chmod(0o755)
    git(repo, "add", "infra/watchdog")
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-m", "Fictional merged source")
    revision = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", revision)
    return repo, revision


def install(repo, *args):
    return subprocess.run(  # noqa: S603 - checked-in installer, private fictional repo
        [BASH, str(repo / INSTALLER_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ["PATH"], "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1"},
    )


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


def assert_refused(result):
    assert result.returncode == 2
    assert result.stderr.strip() == "Refused: unverified watchdog source"
    assert "Verified source" not in result.stdout


def test_verified_installer_dry_run_writes_nothing_and_is_repeatable(installer_repo, tmp_path):
    repo, revision = installer_repo
    # Trap any host-write command; git and sha256sum are the real read-only tools.
    tools = tmp_path / "tools"
    tools.mkdir()
    marker = tmp_path / "host-write-attempt"
    for name in ("sudo", "mktemp", "cp", "mv", "chmod", "chown", "install", "systemctl", "rm"):
        trap = tools / name
        trap.write_text(f"#!/bin/sh\nprintf attempted > {shlex.quote(str(marker))}\nexit 99\n")
        trap.chmod(0o755)
    before = snapshot(repo)
    for args in (("--dry-run",), ()):
        result = subprocess.run(  # noqa: S603 - private repo and host-write traps
            [BASH, str(repo / INSTALLER_PATH), *args, "--source-revision", revision],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": f"{tools}:{os.environ['PATH']}", "LC_ALL": "C"},
        )
        assert result.returncode == 0, result.stderr
        assert revision in result.stdout
        assert hashlib.sha256((repo / SOURCE_PATH).read_bytes()).hexdigest() in result.stdout
        assert "no host files changed" in result.stdout
        assert snapshot(repo) == before
        assert not marker.exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--dry-run"],
        ["--dry-run", "--source-revision"],
        ["--dry-run", "--source-revision", "main"],
        ["--dry-run", "--source-revision", "a" * 7],
        ["--dry-run", "--source-revision", "A" * 40],
        ["--dry-run", "--source-revision", "0" * 40],
        ["--install", "--source-revision", "invalid"],
    ],
)
def test_installer_refuses_missing_invalid_or_unknown_revision(installer_repo, args):
    repo, _ = installer_repo
    before = snapshot(repo)
    assert_refused(install(repo, *args))
    assert snapshot(repo) == before


@pytest.mark.parametrize("path", [SOURCE_PATH, INSTALLER_PATH])
def test_installer_refuses_digest_mismatch_before_any_install(installer_repo, path):
    repo, revision = installer_repo
    with (repo / path).open("a") as altered:
        altered.write("\n# fictional unreviewed change\n")
    before = snapshot(repo)
    assert_refused(install(repo, "--install", "--source-revision", revision))
    assert snapshot(repo) == before


def test_installer_refuses_revision_not_on_main(installer_repo):
    repo, _ = installer_repo
    with (repo / SOURCE_PATH).open("a") as altered:
        altered.write("\n# fictional unmerged change\n")
    git(repo, "add", SOURCE_PATH)
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-m", "Fictional unmerged source")
    revision = git(repo, "rev-parse", "HEAD")
    assert_refused(install(repo, "--dry-run", "--source-revision", revision))


def test_installer_refuses_noncommit_revision(installer_repo):
    repo, _ = installer_repo
    blob = git(repo, "rev-parse", f"HEAD:{SOURCE_PATH}")
    assert_refused(install(repo, "--dry-run", "--source-revision", blob))


def test_installer_refuses_missing_main_evidence(installer_repo):
    repo, revision = installer_repo
    git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    assert_refused(install(repo, "--dry-run", "--source-revision", revision))


@pytest.mark.parametrize("symlink", [False, True])
def test_installer_refuses_missing_or_symlink_source(installer_repo, tmp_path, symlink):
    repo, revision = installer_repo
    source = repo / SOURCE_PATH
    source.unlink()
    if symlink:
        copy = tmp_path / "untracked-source.py"
        shutil.copyfile(ROOT / SOURCE_PATH, copy)
        source.symlink_to(copy)
    assert_refused(install(repo, "--dry-run", "--source-revision", revision))


def test_installer_refuses_duplicate_or_conflicting_options(installer_repo):
    repo, revision = installer_repo
    for args in (
        ["--dry-run", "--install", "--source-revision", revision],
        ["--source-revision", revision, "--source-revision", revision],
        ["--unknown", "--source-revision", revision],
    ):
        assert_refused(install(repo, *args))


@pytest.mark.parametrize("missing", ["api", "billing", "single_review", "syntax"])
def test_installer_refuses_verified_but_stale_source(installer_repo, missing):
    repo, _ = installer_repo
    path = repo / SOURCE_PATH
    source = path.read_text()
    if missing in {"api", "billing"}:
        source = source.replace(f', "{missing}"', "", 1)
    elif missing == "single_review":
        source = source.replace("def single_review(", "def stale_review(", 1)
    else:
        source += "\ndef invalid(:\n"
    # Comments containing all markers cannot make an old implementation eligible.
    path.write_text(source + '\n# LANES = ("api", "billing"); def single_review(\n')
    git(repo, "add", SOURCE_PATH)
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-m", "Fictional stale source")
    revision = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", revision)
    before = snapshot(repo)
    for mode in ("--dry-run", "--install"):
        assert_refused(install(repo, mode, "--source-revision", revision))
        assert snapshot(repo) == before


def test_all_twelve_lanes_match_gate_have_checkouts_and_parse_spec_cards(watchdog):
    expected = ("sales-xray", "platform", "admin", "ui", "devenv", "api", "billing") + tuple(
        FEATURE_REVIEWERS
    )
    assert expected == watchdog.LANES
    tree = ast.parse((ROOT / "scripts/ac_task.py").read_text())
    assert (
        next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign) and node.targets[0].id == "LANES"
        )
        == expected
    )
    for lane in watchdog.LANES:
        assert watchdog.task_lane(f"Lane: {lane}\nTier: routine") == lane
        assert lane in watchdog.LANE_CHECKOUTS
    for lane in FEATURE_REVIEWERS:
        assert watchdog.LANE_CHECKOUTS[lane] == (
            f"/home/acdev/src/lanes/{lane}/authority-closers-platform"
        )


def test_scan_does_not_use_laptop_presence_to_pause_server_agents():
    tree = ast.parse((ROOT / SOURCE_PATH).read_text())
    scan = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "scan"
    )
    names = {node.id for node in ast.walk(scan) if isinstance(node, ast.Name)}
    assert not names & {"LAPTOP_HEARTBEAT", "LAPTOP_AGENTS", "laptop_online"}


@pytest.mark.parametrize(
    "path",
    [
        "packages/python/ac_platform/billing/ledger.py",
        "packages/python/ac_platform/payments/razorpay.py",
        "db/migrations/versions/fictional.py",
        "infra/application/x.sh",
        ".github/workflows/a.yml",
        "scripts/ac_task.py",
        "scripts/ci/merge_class.py",
        "scripts/data-changes/add_member.py",
        "AGENTS.md",
        "apps/sales-xray-web/AGENTS.md",
        "uv.lock",
        "pnpm-lock.yaml",
        "pyproject.toml",
        "pnpm-workspace.yaml",
        "apps/sales-xray-web/package.json",
        "packages/python/ac_platform/http/auth.py",
        "packages/python/ac_platform/http/billing.py",
        "apps/sales-xray-web/app/billing/money.ts",
    ],
)
def test_merge_rule_sensitive_paths(watchdog, path):
    assert watchdog.SENSITIVE_PATH.search(path)


@pytest.mark.parametrize(
    "path",
    [
        "apps/sales-xray-web/app/report-modes.tsx",
        "docs/adr/0053-x.md",
        "packages/python/ac_platform/conversation_intelligence/reports.py",
        "tests/unit/test_reports.py",
        "apps/admin-web/app/page.tsx",
    ],
)
def test_merge_rule_ordinary_paths(watchdog, path):
    assert not watchdog.SENSITIVE_PATH.search(path)


@pytest.mark.parametrize("lane", ["sales-xray", *FEATURE_REVIEWERS])
def test_single_review_respects_cto_pod_lead_and_own_task(watchdog, monkeypatch, lane):
    lead = watchdog.LANE_REVIEWER[lane]
    conn = lambda assignee: SimpleNamespace(  # noqa: E731
        execute=lambda *args: SimpleNamespace(fetchone=lambda: (assignee,))
    )
    monkeypatch.setattr(watchdog, "changed_files", lambda number: ["tests/unit/test_reports.py"])
    assert watchdog.single_review(conn("builder"), 5, "a" * 40, "task", "cto-review") == (
        "the CTO",
        "",
    )
    monkeypatch.setattr(
        watchdog,
        "approval_issue",
        lambda conn, author, *args: "review" if author == lead else None,
    )
    assert watchdog.single_review(conn("builder"), 5, "a" * 40, "task", None) == (
        watchdog.POD_LEAD_IDS[lead],
        "",
    )
    assert watchdog.single_review(conn(lead), 5, "a" * 40, "task", None)[0] is None
    monkeypatch.setattr(watchdog, "approval_issue", lambda *args: None)
    assert watchdog.single_review(conn("builder"), 5, "a" * 40, "task", None) == (
        None,
        "no review yet",
    )
    assert not watchdog.POD_REVIEW_APPROVAL.search("CTO review: approved PR #5 @ abc1234")
    assert watchdog.POD_REVIEW_APPROVAL.search("Review: approved PR #5 @ abc1234")


def test_merge_classifier_change_with_only_cto_review_requires_ceo(watchdog, monkeypatch):
    def github(path):
        if path == "/pulls/5":
            return {"changed_files": 2}
        assert path == "/pulls/5/files?per_page=100&page=1"
        return [
            {"filename": "scripts/ci/merge_class.py"},
            {"filename": "tests/infra/test_merge_class.py"},
        ]

    monkeypatch.setattr(watchdog, "gh_api", github)
    approver, why = watchdog.single_review(None, 5, "a" * 40, "task", "cto-review")
    assert approver is None and "scripts/ci/merge_class.py" in why


# PR #221 (AUT-786: organisation roles and ownership transfer) merged on one review (AUT-932).
PR_221 = [
    "packages/python/ac_platform/http/organisation.py",
    "packages/python/ac_platform/organisations/service.py",
    "tests/integration/test_organisation_owner_transfer_postgresql.py",
    "tests/unit/http/test_organisation_member_writes.py",
]


@pytest.mark.parametrize("files", [PR_221, *[[path] for path in PR_221]])
def test_identity_change_with_only_cto_review_requires_ceo(watchdog, monkeypatch, files):
    def github(path):
        if path == "/pulls/221":
            return {"changed_files": len(files)}
        assert path == "/pulls/221/files?per_page=100&page=1"
        return [{"filename": name} for name in files]

    monkeypatch.setattr(watchdog, "gh_api", github)
    approver, why = watchdog.single_review(None, 221, "a" * 40, "task", "cto-review")
    assert approver is None and files[0] in why


IDENTITY_PARITY = [
    *PR_221,
    "packages/python/ac_platform/identity/models.py",
    "packages/python/ac_platform/tenancy/services.py",
    "packages/python/ac_platform/bootstrap/cli.py",
    "packages/python/ac_platform/media/delivery_authorizer.py",
    "apps/sales-xray-web/app/login/page.tsx",
    "apps/sales-xray-web/app/sign-up.tsx",
    "apps/sales-xray-web/app/sign_out.tsx",
    "apps/sales-xray-web/app/signIn.tsx",
    "apps/sales-xray-web/app/SignOutButton.tsx",
    "apps/admin-web/app/adminRoles.ts",
    "apps/admin-web/app/OAuthCallback.tsx",
    "apps/admin-web/app/people/grants/page.tsx",
    "apps/admin-web/app/workspace-access.tsx",
    "apps/admin-web/app/members/list.tsx",
    "packages/x/jwt.py",
    "packages/x/review_invitations.py",
    "packages/x/session-expired.ts",
    "packages/python/ac_platform/conversation_intelligence/author_notes.py",
    "apps/sales-xray-web/app/authority-closers-logo.svg",
    "docs/authoring-guide.md",
    "packages/python/ac_platform/media/signing.py",
    "apps/sales-xray-web/app/maintenance.tsx",
    "apps/sales-xray-web/app/accessibility.css",
    "apps/sales-xray-web/app/roleplay/page.tsx",
    "apps/sales-xray-web/app/remember-choice.ts",
    "apps/sales-xray-web/app/report-modes.tsx",
]


@pytest.mark.parametrize("case", [str, str.upper])
@pytest.mark.parametrize("path", IDENTITY_PARITY)
def test_identity_rule_matches_merge_classifier(watchdog, path, case):
    sys.path.insert(0, str(ROOT))
    from scripts.ci.merge_class import classify_changed_files

    path = case(path)
    records = [{"filename": path, "status": "modified"}]
    result = classify_changed_files(records, {path: "fictional head"}, changed_files=1)
    assert watchdog.identity_path(path) == ("protected:identity" in result["reasons"])


@pytest.mark.parametrize("files", [None, [], [{"filename": "tests/unit/test_reports.py"}]])
def test_single_review_fails_closed_on_unknown_scope(watchdog, monkeypatch, files):
    monkeypatch.setattr(
        watchdog, "gh_api", lambda path: {"changed_files": 3} if path == "/pulls/5" else files
    )
    assert watchdog.single_review(None, 5, "a" * 40, "task", "cto-review") == (
        None,
        "file list unreadable or incomplete",
    )


def test_threads_per_pr_reviews_and_daily_unassigned_log(watchdog, monkeypatch):
    calls, issues = [], {}

    def act(*args):
        calls.append(args)
        if args[:2] == ("issue", "create"):
            issues[args[args.index("--title") + 1]] = f"id-{len(issues)}"
        return True

    monkeypatch.setattr(watchdog, "act", act)
    monkeypatch.setattr(watchdog, "open_issue_titled", lambda conn, title: issues.get(title))
    state = {"sent": {}}
    names = {watchdog.UI_GUARD_ID: "UI Guard"}
    for key, text in (("k1", "head abc1234"), ("k2", "head def5678")):
        assert watchdog.train_event(
            None, state, names, [], {"kind": "review", "key": key, "text": text, "pr": "180"}
        )
    create, comment = calls
    assert "UI Guard review: studio PR #180" in create
    assert create[create.index("--assignee-agent-id") + 1] == watchdog.UI_GUARD_ID
    assert comment[:3] == ("issue", "comment", "id-0") and "PR #180" in comment[-1]
    assert watchdog.train_event(
        None, state, names, [], {"kind": "status", "key": "s", "text": "staging is current"}
    )
    log, comment = calls[-2:]
    assert log[:2] == ("issue", "create") and "--assignee-agent-id" not in log
    assert log[log.index("--status") + 1] == "backlog"
    assert comment[:2] == ("issue", "comment") and comment[-1] == "staging is current"


@pytest.fixture
def shadow_db():
    """Only fictional temporary tables on the launcher's test DB; always roll back."""
    url = os.environ.get("AC_TEST_DATABASE_URL")
    if not url:
        pytest.skip("AC_TEST_DATABASE_URL is required for watchdog SQL regressions")
    conn = psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"))
    try:
        conn.execute("set local search_path = pg_temp")
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Red main fix: PR #196 @ 37d394e", True),
        ("ok. Red main fix: PR #196 @ `37d394ea8c82`", True),
        ("Red main fix: PR #196 @ 1234567", False),
        ("Red main fix: PR #19 @ 37d394e", False),
        ("Merge approved: PR #196 @ 37d394e", False),
    ],
)
def test_red_main_fix_marker_binds_pr_and_head(watchdog, monkeypatch, body, expected):
    # Port of Root's test_red_main_fix; parsing runs independently of author filtering.
    conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: [(body,)]))
    assert watchdog.red_main_fix(conn, 196, "37d394ea8c82f58ae577ac0a10fb715ce95a3a06") is expected
    assert not watchdog.red_main_fix(SimpleNamespace(), 196, "a" * 40)


@pytest.mark.parametrize(
    ("author", "user", "deleted", "expected"),
    [
        ("CEO_ID", False, False, True),
        ("CTO_ID", False, False, True),
        (None, True, False, True),
        ("CHIEF_ID", False, False, False),
        ("CHIEF_ID", True, False, False),
        (None, False, False, False),
        ("CEO_ID", False, True, False),
    ],
)
def test_red_main_fix_only_accepts_live_ceo_cto_or_board_comments(
    watchdog, shadow_db, author, user, deleted, expected
):
    shadow_db.execute(
        "create temp table issue_comments (body text, author_agent_id uuid, "
        "author_user_id uuid, deleted_at timestamptz)"
    )
    shadow_db.execute(
        "insert into issue_comments values (%s, %s, %s, %s)",
        (
            "Red main fix: PR #196 @ 37d394e",
            getattr(watchdog, author) if author else None,
            uuid.UUID(int=2) if user else None,
            "2026-10-03T00:00:00Z" if deleted else None,
        ),
    )
    assert watchdog.red_main_fix(shadow_db, 196, "37d394e" + "a" * 33) is expected


@pytest.mark.parametrize(
    "lane", ["sales-xray", "platform", "admin", "devenv", "api", *FEATURE_REVIEWERS]
)
def test_review_route_ordinary_lane_and_own_task(watchdog, lane):
    lead = watchdog.LANE_REVIEWER[lane]
    if lane in FEATURE_REVIEWERS:
        assert lead == FEATURE_REVIEWERS[lane]
    assert lead in watchdog.POD_LEAD_IDS
    assert watchdog.review_route(f"task/{lane}/520-fictional", "", "builder") == lead
    assert watchdog.review_route(f"task/{lane}/520-fictional", "", lead) == watchdog.CTO_ID
    assert (
        watchdog.review_route(f"task/{lane}/520-fictional", "sensitive files", "builder")
        == watchdog.CTO_ID
    )


@pytest.mark.parametrize(
    "branch", ["task/ui/296-fictional", "task/billing/878-fictional", "task/9-exclusive"]
)
def test_review_route_without_lane_lead_uses_cto(watchdog, branch):
    assert watchdog.review_route(branch, "", "builder") == watchdog.CTO_ID


@pytest.mark.parametrize(
    ("branch", "files", "own_task", "checks", "expected_lane"),
    [
        (
            "task/platform/850-fictional",
            ["tests/unit/test_reports.py"],
            False,
            "success",
            "platform",
        ),
        (
            "task/api/436-fictional",
            ["packages/python/ac_platform/reports/a.py"],
            False,
            "success",
            "api",
        ),
        ("task/devenv/520-fictional", ["tests/unit/test_reports.py"], False, "success", "devenv"),
        *[
            (f"task/{lane}/1050-fictional", ["tests/unit/test_reports.py"], False, "success", lane)
            for lane in FEATURE_REVIEWERS
        ],
        ("task/platform/850-fictional", ["scripts/ci/merge_class.py"], False, "success", None),
        ("task/platform/850-fictional", None, False, "success", None),
        ("task/platform/850-fictional", ["tests/unit/test_reports.py"], True, "success", None),
        ("task/850-exclusive", ["tests/unit/test_reports.py"], False, "success", None),
        ("task/platform/850-fictional", ["tests/unit/test_reports.py"], False, "failure", None),
    ],
)
def test_green_pr_review_reaches_lane_lead_or_cto_once(
    watchdog, monkeypatch, branch, files, own_task, checks, expected_lane
):
    sha, issue = "a" * 40, "fictional-task"
    calls = []

    def github(path):
        if path.startswith("/pulls?"):
            return [{"number": 1, "head": {"sha": sha, "ref": branch}}]
        assert path == f"/commits/{sha}/check-runs?per_page=100"
        return {
            "check_runs": [
                {
                    "status": "completed",
                    "conclusion": checks,
                    "completed_at": "2026-09-30T00:00:00Z",
                }
            ]
        }

    def query(sql, args):
        assert args == (issue,)
        if "assignee_agent_id" in sql:
            assignee = watchdog.LANE_REVIEWER["platform"] if own_task else "builder"
            return SimpleNamespace(fetchone=lambda: (assignee,))
        return SimpleNamespace(fetchone=lambda: ("AUT-FAKE",))

    monkeypatch.setattr(watchdog, "ACT", True)
    monkeypatch.setattr(watchdog, "gh_api", github)
    monkeypatch.setattr(watchdog, "pr_approvals", lambda *args: (issue, None, None, None, None))
    monkeypatch.setattr(watchdog, "approval_issue", lambda *args: None)
    monkeypatch.setattr(watchdog, "changed_files", lambda number: files)
    monkeypatch.setattr(watchdog, "act", lambda *args: (calls.append(args), True)[1])
    state = {"sent": {}}
    conn = SimpleNamespace(execute=query)
    for _ in range(2):
        watchdog.pull_requests(conn, state, {}, [], "green")
    if checks == "failure":
        assert calls == []
    else:
        reviewer = watchdog.LANE_REVIEWER[expected_lane] if expected_lane else watchdog.CTO_ID
        assert len(calls) == 1
        assert calls[0][:3] == ("issue", "comment", issue)
        assert f"agent://{reviewer}" in calls[0][-1]
        assert "PR #1" in calls[0][-1] and sha[:7] in calls[0][-1]


def test_aut366_picker_never_promotes_backlog_or_recovery_held_tasks(watchdog, shadow_db):
    source = (ROOT / SOURCE_PATH).read_text()
    runnable = re.search(r'runnable = conn\.execute\(\s*"""(.*?)"""', source, re.S).group(1)
    blocked = re.search(
        r'# Blocked work whose blockers are all finished\.\s*for .*?conn\.execute\(\s*"""(.*?)"""',
        source,
        re.S,
    ).group(1)
    conn = shadow_db
    conn.execute("create temp table agents (id uuid primary key, name text)")
    conn.execute(
        "create temp table issues (id uuid primary key, identifier text, title text, status text, "
        "description text, priority text, created_at timestamptz default now(), "
        "hidden_at timestamptz, assignee_agent_id uuid)"
    )
    conn.execute(
        "create temp table issue_relations (issue_id uuid, related_issue_id uuid, type text)"
    )
    conn.execute(
        "create temp table issue_recovery_actions "
        "(source_issue_id uuid, cause text, status text, evidence jsonb)"
    )
    engineer = uuid.uuid4()
    conn.execute("insert into agents values (%s, 'Fictional Engineer')", (engineer,))
    ids = {}
    for ident, status in [
        ("DONE", "done"),
        ("PARKED", "backlog"),
        ("PARKED-NONE", "backlog"),
        ("BLOCKED", "blocked"),
        ("TODO", "todo"),
        ("CANCELLED", "cancelled"),
        ("HELD", "todo"),
        ("RESOLVED", "todo"),
    ]:
        ids[ident] = uuid.uuid4()
        conn.execute(
            "insert into issues (id, identifier, title, status, description, priority, "
            "assignee_agent_id) values (%s, %s, %s, %s, 'Lane: platform', 'high', %s)",
            (ids[ident], ident, ident, status, engineer),
        )
    for ident in ("PARKED", "BLOCKED"):
        conn.execute(
            "insert into issue_relations values (%s, %s, 'blocks')", (ids["DONE"], ids[ident])
        )
    for ident, evidence in (
        ("HELD", '{"automaticRecovery":{"replay":"blocked"}}'),
        ("RESOLVED", "{}"),
    ):
        conn.execute(
            "insert into issue_recovery_actions values "
            "(%s, 'legacy_execution_requires_reconciliation', 'resolved', %s)",
            (ids[ident], evidence),
        )
    rows = conn.execute(runnable).fetchall()
    assert {row[1] for row in rows if row[4]} == {"HELD"}
    assert {row[1] for row in rows if not row[4]} == {"BLOCKED", "TODO", "RESOLVED"}
    assert [row[1] for row in conn.execute(blocked).fetchall()] == ["BLOCKED"]
    conn.execute("update issues set status = 'backlog' where identifier = 'BLOCKED'")
    assert not watchdog.still(conn, str(ids["BLOCKED"]), "blocked")
    assert watchdog.still(conn, str(ids["TODO"]), "todo")
    assert not watchdog.still(conn, str(uuid.uuid4()), "todo")
    assert source.count("not still(conn") == 2


def test_aut303_merge_holds_only_cto_and_ceo_can_hold_or_release(watchdog, shadow_db):
    conn = shadow_db
    conn.execute(
        "create temp table issue_comments (issue_id uuid, author_agent_id uuid, body text, "
        "created_at timestamptz default clock_timestamp())"
    )

    def say(agent, body):
        conn.execute(
            "insert into issue_comments (author_agent_id, body) values (%s, %s)", (agent, body)
        )

    say(watchdog.UI_GUARD_ID, "Merge hold: PR #9")
    assert not watchdog.merge_held(conn, 9)
    say(watchdog.CEO_ID, "Merge hold: PR #9 until fictional copy is checked")
    assert watchdog.merge_held(conn, 9) and not watchdog.merge_held(conn, 90)
    say(watchdog.CTO_ID, "Merge hold released: PR #9")
    assert not watchdog.merge_held(conn, 9)
    say(watchdog.CTO_ID, "Merge hold: PR #9")
    assert watchdog.merge_held(conn, 9)


def test_aut303_approval_lines_and_ui_scope_fail_closed(watchdog, monkeypatch):
    assert watchdog.UI_GUARD_APPROVAL.findall("UI Guard approved: PR #141 @ `abc1234`") == [
        ("141", "abc1234")
    ]
    assert not watchdog.UI_GUARD_APPROVAL.findall("ui guard approved: PR #141 @ abc1234")
    assert [
        (m.group(1), m.group(2))
        for m in watchdog.MERGE_HOLD.finditer("Merge hold: PR #7 ... Merge hold released: PR #7")
    ] == [(None, "7"), (" released", "7")]

    def scope(files, changed=None, threads=0, fail=False):
        def github(path):
            if fail:
                raise OSError("fictional outage")
            if path.startswith("/pulls/1/files"):
                page = int(path.rsplit("page=", 1)[1])
                return [{"filename": f} for f in files[(page - 1) * 100 : page * 100]]
            return {"changed_files": len(files) if changed is None else changed}

        monkeypatch.setattr(watchdog, "gh_api", github)
        monkeypatch.setattr(watchdog, "unresolved_threads", lambda number: threads)
        return watchdog.ui_guard_scope(1)

    ok = ["apps/sales-xray-web/app/dashboard/page.tsx", "apps/sales-xray-web/public/logo.svg"]
    assert scope(ok) == ""
    assert scope([f"apps/sales-xray-web/app/x{i}.tsx" for i in range(250)]) == ""
    for path in [
        "apps/sales-xray-web/package.json",
        "infra/release/x.py",
        "apps/sales-xray-web/app/tests/a.test.tsx",
        "apps/sales-xray-web/app/AGENTS.md",
        "apps/sales-xray-web/app/CLAUDE.md",
        "apps/sales-xray-web/app/tsconfig.json",
        "apps/sales-xray-web/app/next.config.ts",
        "apps/sales-xray-web/app/vitest.config.ts",
        "apps/sales-xray-web/app/eslint.config.mjs",
        "apps/sales-xray-web/public/package.json",
        "apps/sales-xray-web/app/members/page.tsx",
        "apps/sales-xray-web/app/sign-in/page.tsx",
        "apps/sales-xray-web/app/SignOutButton.tsx",
    ]:
        assert "outside" in scope(ok + [path])
    assert scope(ok, changed=5) == scope([]) == "file list incomplete"
    assert scope(ok, fail=True) == "file list unreadable"
    assert scope(ok, threads=1).startswith("unresolved")
    assert scope(ok, threads=None).startswith("unresolved")


@pytest.mark.parametrize(
    ("approval", "file", "held", "main", "marked_fix", "expected"),
    [
        ("guard", "apps/sales-xray-web/app/page.tsx", False, "green", False, True),
        ("guard", "apps/sales-xray-web/package.json", False, "green", False, False),
        ("guard", "apps/sales-xray-web/app/page.tsx", True, "green", False, False),
        ("ceo", "infra/x.py", True, "green", False, False),
        ("guard", "apps/sales-xray-web/app/page.tsx", False, "running", False, True),
        ("guard", "apps/sales-xray-web/app/page.tsx", False, "red", False, False),
        ("ceo", "infra/x.py", False, "green", False, True),
        ("cto", "apps/sales-xray-web/app/page.tsx", False, "green", False, True),
        ("cto", "db/migrations/versions/x.py", False, "green", False, False),
        ("cto", "scripts/ci/merge_class.py", False, "green", False, False),
        ("guard", "apps/sales-xray-web/app/members/page.tsx", False, "green", False, False),
        ("guard", "apps/sales-xray-web/app/sign-in/page.tsx", False, "green", False, False),
        ("cto", "apps/sales-xray-web/app/members/page.tsx", False, "green", False, False),
        ("ceo", "apps/sales-xray-web/app/sign-in/page.tsx", False, "green", False, True),
        ("ceo", "infra/x.py", False, "red", True, True),
        ("ceo", "infra/x.py", False, "red", False, False),
        ("ceo", "infra/x.py", True, "red", True, False),
        ("ceo", "infra/x.py", False, None, True, False),
        ("cto", "tests/unit/test_reports.py", False, "red", True, True),
        ("cto", "scripts/ci/merge_class.py", False, "red", True, False),
        (None, "tests/unit/test_reports.py", False, "red", True, False),
    ],
)
def test_aut303_pr_merge_routes(
    watchdog, monkeypatch, approval, file, held, main, marked_fix, expected
):
    sha = "a" * 40
    calls = []

    def github(path):
        if path.startswith("/pulls?"):
            return [
                {
                    "number": 1,
                    "head": {"sha": sha, "ref": "task/platform/fictional"},
                    "updated_at": "2026-09-30T00:00:00Z",
                }
            ]
        if "/check-runs" in path:
            return {"check_runs": [{"status": "completed", "conclusion": "success"}]}
        if path.startswith("/pulls/1/files"):
            return [{"filename": file}]
        return {"changed_files": 1}

    monkeypatch.setattr(watchdog, "gh_api", github)
    monkeypatch.setattr(watchdog, "unresolved_threads", lambda number: 0)
    monkeypatch.setattr(watchdog, "ACT", True)
    monkeypatch.setattr(
        watchdog,
        "pr_approvals",
        lambda *args: (
            "task",
            "review" if approval == "cto" else None,
            "approval" if approval == "ceo" else None,
            None,
            "guard" if approval == "guard" else None,
        ),
    )
    monkeypatch.setattr(watchdog, "merge_held", lambda *args: held)
    monkeypatch.setattr(watchdog, "red_main_fix", lambda *args: marked_fix)
    monkeypatch.setattr(watchdog, "approval_issue", lambda *args: None)
    monkeypatch.setattr(watchdog, "act", lambda *args: True)
    monkeypatch.setattr(watchdog.tg, "paperclip", lambda *args: (True, ""))
    monkeypatch.setattr(watchdog, "merge", lambda *args: (calls.append(args), (True, ""))[1])
    conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: ("AUT-FAKE",)))
    watchdog.pull_requests(conn, {"sent": {}}, {}, [], main)
    assert calls == ([(1, sha, "task/platform/fictional")] if expected else [])


@pytest.mark.parametrize(
    ("previous", "eligible"),
    [
        ("apps/sales-xray-web/app/old-page.tsx", True),
        ("apps/sales-xray-web/app/members/page.tsx", False),
        ("apps/sales-xray-web/app/signIn.tsx", False),
    ],
)
def test_ui_guard_scope_checks_rename_sources_for_identity(
    watchdog, monkeypatch, previous, eligible
):
    # AUT-932: a rename out of an identity path is still an identity change.
    def github(path):
        if path.startswith("/pulls/1/files"):
            return [
                {
                    "filename": "apps/sales-xray-web/app/dashboard/page.tsx",
                    "previous_filename": previous,
                }
            ]
        return {"changed_files": 1}

    monkeypatch.setattr(watchdog, "gh_api", github)
    monkeypatch.setattr(watchdog, "unresolved_threads", lambda number: 0)
    why = watchdog.ui_guard_scope(1)
    assert (why == "") is eligible
    assert eligible or previous in why


def test_aut303_spools_deduplicate_retry_and_archive(watchdog, monkeypatch, shadow_db, tmp_path):
    conn = shadow_db
    conn.execute(
        "create temp table issues (id uuid primary key, company_id uuid, identifier text, "
        "status text, description text, hidden_at timestamptz, "
        "created_at timestamptz default now(), title text)"
    )
    posted = []

    def act(*args):
        posted.append(args)
        if args[:2] == ("issue", "create"):
            fields = dict(zip(args[2::2], args[3::2], strict=True))
            conn.execute(
                "insert into issues (id, company_id, identifier, status, description, title) "
                "values (%s, %s, 'AUT-FAKE', %s, %s, %s)",
                (
                    uuid.uuid4(),
                    watchdog.tg.COMPANY,
                    fields["--status"],
                    fields["--description"],
                    fields["--title"],
                ),
            )
        return True

    monkeypatch.setattr(watchdog, "act", act)
    monkeypatch.setattr(watchdog, "ACT", True)
    monkeypatch.setattr(watchdog.tg, "esc", lambda text: text, raising=False)
    release, studio = tmp_path / "release", tmp_path / "studio"
    release.mkdir()
    studio.mkdir()
    monkeypatch.setattr(watchdog, "TRAIN_SPOOLS", (release, studio, tmp_path / "missing"))
    state = {"sent": {}}

    def emit(spool, kind, key, text, name="event.json", **fields):
        (spool / name).write_text(json.dumps({"kind": kind, "key": key, "text": text, **fields}))

    emit(release, "alert", "r1_test", "R1 fictional alert", "alert.json")
    emit(release, "status", "s", "fictional staging is current", "status.json")
    emit(studio, "review", "pr-141", "fictional slice", "review.json", pr=141)
    (studio / "broken.json").write_text("{broken")
    watchdog.train_events(conn, state, {}, [])
    creates = [args for args in posted if args[:2] == ("issue", "create")]
    assert len(creates) == 3
    assert any(
        "Train alert: R1 fictional alert" in args
        and "critical" in args
        and watchdog.DEV_LEAD_ID in args
        for args in creates
    )
    assert any(
        "UI Guard review: studio PR #141" in args and watchdog.UI_GUARD_ID in args
        for args in creates
    )
    logs = [args for args in creates if "backlog" in args]
    assert len(logs) == 1 and "--assignee-agent-id" not in logs[0]
    assert not list(release.glob("*.json")) and not list(studio.glob("*.json"))
    assert len(list((release / "done").glob("*.json"))) == 2
    assert len(list((studio / "done").glob("*.json"))) == 2
    posted.clear()
    emit(release, "alert", "r1_test", "R1 fictional alert")
    watchdog.train_events(conn, state, {}, [])
    assert posted == [] and not list(release.glob("*.json"))
    state["sent"]["train-alert:r1_test"] = time.time() - 7 * 3600
    emit(release, "alert", "r1_test", "R1 fictional alert")
    watchdog.train_events(conn, state, {}, [])
    assert [args[:2] for args in posted] == [("issue", "comment")]
    posted.clear()
    emit(release, "alert", "r1Xtest", "different fictional key")
    watchdog.train_events(conn, state, {}, [])
    assert [args[:2] for args in posted] == [("issue", "create")]
    conn.execute("update issues set status = 'done'")
    posted.clear()
    emit(release, "alert", "r1_test", "R1 fictional alert")
    watchdog.train_events(conn, state, {}, [])
    assert [args[:2] for args in posted] == [("issue", "create")]
    monkeypatch.setattr(watchdog, "act", lambda *args: False)
    emit(release, "status", "s2", "retry fictional status")
    watchdog.train_events(conn, state, {}, [])
    assert (release / "event.json").exists()
    old = next((release / "done").glob("*.json"))
    os.utime(old, (time.time() - 8 * 86400,) * 2)
    monkeypatch.setattr(watchdog, "act", act)
    watchdog.train_events(conn, state, {}, [])
    assert not old.exists() and not (release / "event.json").exists()
    monkeypatch.setattr(watchdog, "ACT", False)
    emit(release, "status", "s3", "fictional dry run")
    watchdog.train_events(conn, state, {}, [])
    assert (release / "event.json").exists()
