"""Studio preservation against real Git repositories; only gh and the gate are faked."""

import configparser
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/development/ac-studio-sync.py"
SPEC = importlib.util.spec_from_file_location("studio_sync", SCRIPT)
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)
APP = "apps/sales-xray-web/app/"
PUBLIC = "apps/sales-xray-web/public/"
BRANCH = "task/ui/296-studio-202609300000"


class Harness:
    def __init__(self, path):
        self.repo, self.remote = path / "repo", path / "remote.git"
        self.repo.mkdir()
        self.state, self.spool = path / "state.json", path / "spool"
        self.now = time.time() + 1000
        self.prs, self.comments, self.calls = [], [], []
        self.busy = False
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.write(APP + "page.tsx", "original\n")
        self.write(PUBLIC + "old.svg", "old\n")
        self.write("README.md", "unrelated\n")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        SYNC.command(["git", "init", "--bare", str(self.remote)], cwd=self.repo)
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-u", "origin", "main")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return SYNC.command(["git", *args], cwd=self.repo).strip()

    def write(self, path, text):
        file = self.repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
        os.utime(file, (self.now - 300, self.now - 300))
        return file

    def branch(self, name=BRANCH):
        self.git("switch", "-c", name)
        self.git("push", "-u", "origin", name)

    def make_pr(self, state="OPEN", age=0):
        item = {
            "number": 17,
            "state": state,
            "headRefOid": self.git("rev-parse", "HEAD"),
            "createdAt": SYNC.stamp(self.now - age),
        }
        self.prs = [item]
        return item

    def runner(self, argv, *, cwd, env=None, input_data=None):
        self.calls.append(argv)
        if argv[0] == "gh":
            if argv[1:3] == ["pr", "list"]:
                return json.dumps(self.prs)
            if argv[1:3] == ["pr", "create"]:
                assert argv[argv.index("--body") + 1].startswith("Task: AUT-296")
                self.make_pr()
                return "https://example.invalid/pr/17"
            if argv[1] == "api":
                return json.dumps([self.comments])
            pytest.fail(str(argv))
        if argv[0] == sys.executable and argv[1] == "scripts/ac_task.py":
            if argv[2] == "done":
                assert not self.git("status", "--porcelain")
                self.git("switch", "main")
                self.git("fetch", "origin")
                self.git("merge", "--ff-only", "origin/main")
            else:
                if self.busy:
                    raise SYNC.SyncError("gate BUSY")
                assert not self.git("status", "--porcelain")
                self.git("fetch", "origin")
                self.git("switch", "-c", "task/ui/" + argv[-1], "origin/main")
                self.git("push", "-u", "origin", "HEAD")
            return ""
        return SYNC.command(argv, cwd=cwd, env=env, input_data=input_data)

    def tick(self, commit_only=False):
        sync = SYNC.Sync(self.repo, self.state, self.spool, runner=self.runner, now=self.now)
        sync.tick(commit_only)
        return sync

    def events(self, kind=None):
        events = [json.loads(p.read_text()) for p in self.spool.glob("*.json")]
        return [e for e in events if kind is None or e["kind"] == kind]

    def remote_head(self, branch=BRANCH):
        return self.git("ls-remote", "origin", "refs/heads/" + branch).split()[0]


@pytest.fixture
def repo(tmp_path):
    return Harness(tmp_path)


def test_allowlist_untracked_deletion_and_staged_stray(repo):
    repo.branch()
    repo.write(APP + "page.tsx", "updated\n")
    repo.write(PUBLIC + "new.svg", "new\n")
    (repo.repo / (PUBLIC + "old.svg")).unlink()
    repo.write("README.md", "keep staged\n")
    repo.git("add", "README.md")
    repo.tick(commit_only=True)
    assert repo.git("show", "HEAD:README.md") == "unrelated"
    assert repo.git("diff", "--cached", "--name-only") == "README.md"
    assert set(
        repo.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
    ) == {APP + "page.tsx", PUBLIC + "new.svg", PUBLIC + "old.svg"}
    assert repo.git("log", "-1", "--format=%an <%ae>") == "UI Studio <studio@paperclip.ing>"
    assert repo.events("alert")
    assert not any(c[0] == "gh" for c in repo.calls)
    assert repo.remote_head() == repo.base


@pytest.mark.parametrize(
    "name,text",
    [
        (".env.local", "value"),
        ("secret.pem", "value"),
        ("secret.key", "value"),
        ("id_private", "value"),
        ("token.txt", "ghp_" + "fake"),
        ("token.txt", "github_pat_" + "fake"),
        ("token.txt", "sk-" + "fake"),
        ("token.txt", "AKIA" + "fake"),
        ("token.txt", "-----BEGIN" + " FAKE"),
        pytest.param("large.txt", "a" * (SYNC.LIMIT + 1), id="over-one-mib"),
    ],
)
def test_refusals_skip_file_and_still_commit_screens(repo, name, text):
    repo.branch()
    repo.write(APP + name, text)
    repo.write(APP + "page.tsx", "safe")
    repo.tick(True)
    assert repo.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD") == APP + "page.tsx"
    assert repo.events("alert")
    assert all(text not in json.dumps(event) for event in repo.events())


def test_symlink_is_not_committed(repo):
    repo.branch()
    (repo.repo / (APP + "link")).symlink_to(repo.repo / "README.md")
    repo.write(APP + "page.tsx", "safe")
    repo.tick(True)
    assert APP + "link" not in repo.git("ls-tree", "-r", "--name-only", "HEAD")


def test_main_checkpoint_tag_and_new_slice(repo):
    repo.write(APP + "page.tsx", "preserved")
    repo.tick()
    assert repo.git("branch", "--show-current").startswith(SYNC.STUDIO)
    assert "refs/tags/archive/studio-" in repo.git("ls-remote", "--tags", "origin")
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "preserved"
    assert repo.git("rev-parse", "main") == repo.base
    assert not repo.git("status", "--porcelain")
    assert "pending" not in json.loads(repo.state.read_text())
    assert any("cherry-pick" in call for call in repo.calls)


def test_main_requires_two_quiet_minutes(repo):
    file = repo.write(APP + "page.tsx", "still editing")
    os.utime(file, (repo.now - 119, repo.now - 119))
    repo.tick()
    assert repo.git("rev-parse", "HEAD") == repo.base
    assert not repo.git("tag")


def test_busy_retry_keeps_checkpoint_and_alerts_once_after_two_hours(repo):
    repo.busy = True
    repo.write(APP + "page.tsx", "first")
    repo.tick()
    first = repo.git("rev-parse", "HEAD")
    assert first != repo.base and not repo.events("alert")
    repo.now += 7200
    repo.write(APP + "page.tsx", "second")
    repo.tick()
    assert len(repo.events("alert")) == 1
    repo.now += 1800
    repo.tick()
    assert len(repo.events("alert")) == 1
    repo.busy = False
    repo.now += 1800
    repo.tick()
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "second"
    assert "pending" not in json.loads(repo.state.read_text())


def test_pacing_stable_head_and_maximum_once_every_two_hours(repo):
    repo.branch()
    repo.make_pr()
    repo.write(APP + "page.tsx", "edit")
    repo.tick()
    assert not repo.events("review")
    repo.now += 1800
    repo.tick()
    assert len(repo.events("review")) == 1
    repo.now += 7199
    repo.tick()
    assert len(repo.events("review")) == 1
    repo.now += 1
    repo.tick()
    assert len(repo.events("review")) == 2


def test_old_pr_review_despite_changing_head(repo):
    repo.branch()
    repo.make_pr(age=7200)
    repo.write(APP + "page.tsx", "edit")
    repo.tick()
    assert len(repo.events("review")) == 1


@pytest.mark.parametrize("transport", ["comment", "state"])
def test_approved_published_head_freezes_push_across_local_commits(repo, transport):
    repo.branch()
    pr = repo.make_pr()
    if transport == "comment":
        repo.comments = [{"body": f"UI Guard approved: PR #17 @ {pr['headRefOid'][:7]}"}]
    else:
        repo.state.write_text(json.dumps({"approvals": {"17": pr["headRefOid"]}}))
    for text in ("one", "two"):
        repo.write(APP + "page.tsx", text)
        repo.tick()
        repo.now += 1800
    assert repo.remote_head() == pr["headRefOid"]
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "two"
    assert not repo.events("review")


def test_hand_started_slice_never_requests_review(repo):
    repo.branch("task/ui/123-hand-started")
    repo.make_pr(age=8000)
    repo.write(APP + "page.tsx", "edit")
    repo.tick()
    assert not repo.events("review")


@pytest.mark.parametrize(
    "marker", ["rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD"]
)
def test_unfinished_operation_refuses_before_git_writes(repo, marker):
    repo.branch()
    (repo.repo / ".git" / marker).touch()
    repo.write(APP + "page.tsx", "edit")
    with pytest.raises(SYNC.SyncError, match="no Git writes"):
        repo.tick()
    assert repo.git("rev-parse", "HEAD") == repo.base
    assert not any("add" in c or "commit" in c or "push" in c for c in repo.calls)


@pytest.mark.parametrize("branch", ["task/admin/123-other", None])
def test_other_lane_or_detached_head_refuses(repo, branch):
    if branch:
        repo.branch(branch)
    else:
        repo.git("switch", "--detach")
    with pytest.raises(SYNC.SyncError, match="no Git writes"):
        repo.tick()


def test_merged_pr_carries_unpublished_commits(repo):
    repo.branch()
    repo.write(APP + "page.tsx", "approved")
    repo.tick(True)
    approved = repo.git("rev-parse", "HEAD")
    repo.git("push", "origin", "HEAD")
    pr = repo.make_pr("MERGED")
    repo.git("push", "origin", f"{approved}:refs/heads/main", f"{approved}:refs/pull/17/head")
    repo.write(APP + "page.tsx", "unpublished")
    repo.tick(True)
    repo.tick()
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "unpublished"
    assert repo.git("branch", "--show-current") != BRANCH
    assert repo.git("rev-list", "--count", "origin/main..HEAD") == "1"
    assert pr["headRefOid"] == approved


def test_source_has_no_forbidden_git_operations():
    source = SCRIPT.read_text()
    for forbidden in (
        "stash",
        "--hard",
        '"clean"',
        '"checkout"',
        '"--force"',
        '"--force-with-lease"',
    ):
        assert forbidden not in source


def test_units_parse_and_limit_resources():
    service, timer = configparser.ConfigParser(interpolation=None), configparser.ConfigParser()
    service.read(SCRIPT.with_suffix(".service"))
    timer.read(SCRIPT.with_suffix(".timer"))
    values = service["Service"]
    assert values["User"] == "acdev"
    assert values["TimeoutStartSec"] == "300"
    assert values["MemoryMax"] == "256M"
    assert "Restart" not in values
    assert values["CPUQuota"] == "25%"
    assert timer["Timer"]["OnUnitActiveSec"] == "30min"


def test_github_outage_still_commits_screen_edits(repo):
    repo.branch()
    repo.write(APP + "page.tsx", "safe during outage")
    original = repo.runner

    def failing(argv, **kwargs):
        if argv[0] == "gh":
            raise SYNC.SyncError("gh failed; inspect locally")
        return original(argv, **kwargs)

    repo.runner = failing
    with pytest.raises(SYNC.SyncError, match="gh failed"):
        repo.tick()
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "safe during outage"


def test_busy_after_merge_retains_carry_over_and_subsequent_main_edits(repo):
    repo.branch()
    repo.make_pr("MERGED")
    repo.git("push", "origin", f"{repo.base}:refs/pull/17/head")
    repo.write(APP + "page.tsx", "unpublished")
    repo.tick(True)
    repo.busy = True
    repo.tick()
    assert repo.git("branch", "--show-current") == "main"
    repo.write(PUBLIC + "later.svg", "new while busy")
    repo.now += 1800
    repo.tick()
    repo.now += 1800
    repo.busy = False
    repo.tick()
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "unpublished"
    assert repo.git("show", "HEAD:" + PUBLIC + "later.svg") == "new while busy"
    assert not repo.git("status", "--porcelain")


def test_main_commit_only_and_later_tick_retain_checkpoint(repo):
    repo.write(APP + "page.tsx", "checkpoint")
    repo.tick(True)
    checkpoint = repo.git("rev-parse", "HEAD")
    assert checkpoint != repo.base
    assert repo.git("branch", "--show-current") == "main"
    assert not repo.git("tag")
    assert not any(c[0] == "gh" or "push" in c for c in repo.calls)
    repo.now += 1800
    repo.tick()
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "checkpoint"
    assert repo.git("rev-parse", "main") == repo.base


def test_recent_deletion_is_not_a_quiet_main(repo):
    (repo.repo / (PUBLIC + "old.svg")).unlink()
    os.utime(repo.repo / PUBLIC, (repo.now, repo.now))
    repo.tick()
    assert repo.git("rev-parse", "HEAD") == repo.base


def test_exact_index_blob_is_scanned_and_later_edits_remain_uncommitted(repo):
    repo.branch()
    repo.write(APP + "page.tsx", "safe snapshot")
    original = repo.runner

    def changing(argv, **kwargs):
        result = original(argv, **kwargs)
        if argv[:3] == ["git", "--literal-pathspecs", "hash-object"]:
            repo.write(APP + "page.tsx", "sk-" + "fake-after-stage")
        return result

    repo.runner = changing
    repo.tick(True)
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "safe snapshot"
    assert repo.git("diff", "--name-only") == APP + "page.tsx"
    repo.tick(True)
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "safe snapshot"
    assert repo.events("alert")


def test_main_stray_preserves_screen_checkpoint_and_staged_stray(repo):
    repo.write(APP + "page.tsx", "preserved")
    repo.write("README.md", "stray")
    repo.git("add", "README.md")
    repo.busy = True
    repo.tick()
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "preserved"
    assert repo.git("diff", "--cached", "--name-only") == "README.md"
    assert repo.events("alert")[0]["key"] == "outside-allowlist"
    assert repo.git("ls-remote", "--tags", "origin")


def test_interrupted_replay_refuses_without_losing_archived_edits(repo):
    repo.write(APP + "page.tsx", "archived")
    original = repo.runner

    def interrupted(argv, **kwargs):
        if "cherry-pick" in argv:
            raise SYNC.SyncError("interrupted replay")
        return original(argv, **kwargs)

    repo.runner = interrupted
    with pytest.raises(SYNC.SyncError, match="interrupted replay"):
        repo.tick()
    state = json.loads(repo.state.read_text())
    assert repo.git("show", state["pending"]["archive"] + ":" + APP + "page.tsx") == "archived"
    repo.runner = original
    with pytest.raises(SYNC.SyncError, match="local recovery"):
        repo.tick()


def test_cli_respects_shared_flock_and_refusal_spool(repo, monkeypatch):
    import fcntl
    from types import SimpleNamespace

    monkeypatch.setattr(SYNC.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(SYNC.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_name="acdev"))
    lockfile = repo.repo.parent / "lock"
    args = [
        "--repo",
        str(repo.repo),
        "--state",
        str(repo.state),
        "--spool",
        str(repo.spool),
        "--lock",
        str(lockfile),
        "--commit-only",
    ]
    repo.branch("task/admin/123-other")
    with lockfile.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert SYNC.main(args) == 75
        assert not repo.events()
    assert SYNC.main(args) == 1
    event = repo.events("alert")[0]
    assert set(event) == {"kind", "key", "at", "text"}
    assert "no Git writes" in event["text"]
    assert len(list(repo.spool.iterdir())) == 1


def test_root_is_refused_before_lock_or_git(repo, monkeypatch):
    monkeypatch.setattr(SYNC.os, "geteuid", lambda: 0)
    with pytest.raises(SystemExit) as error:
        SYNC.main(["--repo", str(repo.repo), "--lock", str(repo.repo / "never-created")])
    assert error.value.code == 2
    assert not (repo.repo / "never-created").exists()


def test_main_deletion_of_entire_screen_directory(repo):
    (repo.repo / (APP + "page.tsx")).unlink()
    (repo.repo / APP).rmdir()
    repo.tick()
    assert APP + "page.tsx" not in repo.git("ls-tree", "-r", "--name-only", "HEAD")
    assert not repo.git("status", "--porcelain")


def test_broken_alert_spool_does_not_block_screen_commit(repo):
    repo.branch()
    repo.write(APP + "page.tsx", "preserved despite spool failure")
    repo.write("README.md", "stray")
    repo.spool.write_text("not a directory")
    sync = repo.tick(True)
    assert sync.notification_failed
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "preserved despite spool failure"
    assert repo.git("diff", "--name-only") == "README.md"


def test_refused_content_is_not_written_to_git_object_store(repo):
    repo.branch()
    payload = b"github_pat_" + b"fictional-refused-fixture"
    repo.write(APP + "credential.txt", payload.decode())
    oid = SYNC.command(["git", "hash-object", "--stdin"], cwd=repo.repo, input_data=payload).strip()
    repo.write(APP + "page.tsx", "safe")
    repo.tick(True)
    with pytest.raises(SYNC.SyncError):
        repo.git("cat-file", "-e", oid)


def test_literal_filenames_and_binary_assets(repo):
    repo.branch()
    strange = APP + "[draft]*\npage.tsx"
    repo.write(strange, "literal name")
    binary = PUBLIC + "asset.bin"
    data = bytes([255, 0, 128, 1])
    (repo.repo / binary).write_bytes(data)
    repo.tick(True)
    assert repo.git("show", "HEAD:" + strange) == "literal name"
    assert repo.git("show", "HEAD:" + binary).encode("utf-8", "surrogateescape") == data


def test_stale_approval_does_not_freeze_new_head(repo):
    repo.branch()
    repo.make_pr()
    repo.comments = [{"body": "Merge approved: PR #17 @ 0000000"}]
    repo.write(APP + "page.tsx", "new")
    repo.tick()
    assert repo.remote_head() == repo.git("rev-parse", "HEAD")


def test_refresh_inherited_lock_commits_and_remains_locked_for_merge(repo, monkeypatch):
    import fcntl
    from types import SimpleNamespace

    monkeypatch.setattr(SYNC.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(SYNC.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_name="acdev"))
    repo.branch()
    repo.write(APP + "page.tsx", "save before refresh merge")
    lockfile = repo.repo.parent / "refresh.lock"
    with lockfile.open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        args = [
            "--repo",
            str(repo.repo),
            "--state",
            str(repo.state),
            "--spool",
            str(repo.spool),
            "--lock",
            str(lockfile),
            "--lock-fd",
            str(owner.fileno()),
            "--commit-only",
        ]
        assert SYNC.main(args) == 0
        assert repo.git("show", "HEAD:" + APP + "page.tsx") == "save before refresh merge"
        with lockfile.open("a") as competitor, pytest.raises(BlockingIOError):
            fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_inherited_lock_must_match_lock_path(repo, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(SYNC.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(SYNC.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_name="acdev"))
    lockfile = repo.repo.parent / "real.lock"
    lockfile.touch()
    with (repo.repo.parent / "wrong.lock").open("a") as other, pytest.raises(SystemExit) as error:
        SYNC.main(["--lock", str(lockfile), "--lock-fd", str(other.fileno())])
    assert error.value.code == 2


def test_commit_only_reports_quiet_window_deferral_to_refresh(repo, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(SYNC.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(SYNC.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_name="acdev"))
    file = repo.write(APP + "page.tsx", "actively editing")
    os.utime(file, None)
    result = SYNC.main(
        [
            "--repo",
            str(repo.repo),
            "--state",
            str(repo.state),
            "--spool",
            str(repo.spool),
            "--lock",
            str(repo.repo.parent / "quiet.lock"),
            "--commit-only",
        ]
    )
    assert result == 75
    assert repo.git("rev-parse", "HEAD") == repo.base
