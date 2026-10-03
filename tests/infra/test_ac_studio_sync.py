"""Studio preservation against real Git repositories; only gh and the gate are faked."""

import configparser
import importlib.util
import json
import os
import subprocess
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
FAKE_TOKENS = [
    "ghp_" + "F" * 36,
    "github_pat_" + "F" * 30,
    "sk-" + "F" * 24,
    "AKIA" + "F" * 16,
    "-----BEGIN" + " RSA PRIVATE KEY-----",
    "cfat_" + "F" * 24,
    "re_" + "F" * 24,
]


class Harness:
    def __init__(self, path):
        self.repo, self.remote = path / "repo", path / "remote.git"
        self.repo.mkdir()
        self.state, self.spool = path / "state.json", path / "spool"
        self.now = int(time.time()) + 1000
        self.prs, self.comments, self.calls = [], [], []
        self.busy = self.done_busy = False
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
                if self.done_busy:
                    raise SYNC.SyncError("gate done BUSY")
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


@pytest.fixture
def prettier(repo):
    repo.write(".git/info/exclude", "node_modules/\n")
    return repo.write("node_modules/.bin/prettier", "")


@pytest.mark.parametrize("hold", [None, BRANCH])
def test_prettier_formats_changed_allowed_files_before_index(repo, prettier, hold):
    repo.branch()
    screen = APP + "[call id]/report.module.css"
    fixture = SYNC.FIXTURES + "report.json"
    repo.write(screen, ".report{color:red}")
    repo.write(fixture, '{"report":true}')
    repo.write("README.md", "keep staged\n")
    repo.git("add", "README.md")
    (repo.repo / (PUBLIC + "old.svg")).unlink()
    repo.write(APP + "secret.key", "refused")
    repo.write(APP + "refused.css", FAKE_TOKENS[0])
    (repo.repo / (APP + "link.css")).symlink_to(repo.repo / "README.md")
    original = repo.runner
    formatted = {screen: ".report {\n  color: red;\n}\n", fixture: '{ "report": true }\n'}

    def formatting(argv, **kwargs):
        if argv[0] == str(prettier):
            repo.calls.append(argv)
            assert argv[1:] == ["--write", "--ignore-unknown", "--", screen, fixture]
            for path, content in formatted.items():
                repo.write(path, content)
            return ""
        return original(argv, **kwargs)

    repo.runner = formatting
    sync = SYNC.Sync(repo.repo, repo.state, repo.spool, runner=repo.runner, now=repo.now)
    result = sync.commit(sync.paths(), hold=hold)
    ref = result if hold else "HEAD"
    for path, content in formatted.items():
        assert repo.git("show", ref + ":" + path) == content.strip()
    assert repo.git("diff", "--cached", "--name-only") == "README.md"
    assert repo.git("show", ref + ":" + APP + "page.tsx") == "original"
    assert PUBLIC + "old.svg" not in repo.git("ls-tree", "-r", "--name-only", ref)
    format_call = next(i for i, call in enumerate(repo.calls) if call[0] == str(prettier))
    index_call = next(i for i, call in enumerate(repo.calls) if "read-tree" in call)
    assert format_call < index_call


def test_missing_prettier_logs_skip_and_preserves_commit(repo, capsys):
    repo.branch()
    repo.write(APP + "page.tsx", "preserved")
    repo.tick(True)
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "preserved"
    assert "Pinned Prettier unavailable; skipping screen formatting." in capsys.readouterr().err
    assert not any("--write" in call for call in repo.calls)


@pytest.mark.parametrize(
    "error",
    [
        SYNC.SyncError("formatter output must stay private"),
        FileNotFoundError("formatter output must stay private"),
        subprocess.TimeoutExpired("formatter output must stay private", 45),
    ],
)
def test_prettier_failure_does_not_block_preservation(repo, prettier, capsys, error):
    repo.branch()
    repo.write(APP + "page.tsx", "preserved")
    original = repo.runner

    def failing(argv, **kwargs):
        if argv[0] == str(prettier):
            raise error
        return original(argv, **kwargs)

    repo.runner = failing
    repo.tick(True)
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "preserved"
    logged = capsys.readouterr().err
    assert "Pinned Prettier failed; skipping screen formatting." in logged
    assert "formatter output must stay private" not in logged


def test_formatted_bytes_are_scanned_again_before_commit(repo, prettier):
    repo.branch()
    repo.write(APP + "report.module.css", ".report{color:red}")
    repo.write(APP + "page.tsx", "safe")
    original = repo.runner

    def formatting(argv, **kwargs):
        if argv[0] == str(prettier):
            repo.write(APP + "report.module.css", FAKE_TOKENS[0])
            return ""
        return original(argv, **kwargs)

    repo.runner = formatting
    repo.tick(True)
    assert repo.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD") == APP + "page.tsx"
    assert repo.events("alert")


@pytest.mark.parametrize(
    "name,text",
    [
        (".env.local", "value"),
        ("secret.pem", "value"),
        ("secret.key", "value"),
        ("id_private", "value"),
        *[("token.txt", token) for token in FAKE_TOKENS],
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


def test_lane_pr_branch_holds_edits_in_local_checkpoint_and_alerts_once(repo):
    # AUT-864: #185's approvals lived on Paperclip, so the freeze above did not see them.
    lane = "task/ui/441-sales-xray-workspaces"
    repo.branch(lane)
    pr = repo.make_pr(age=8000)
    for text in ("one", "two"):
        repo.write(APP + "page.tsx", text)
        repo.tick()
        repo.now += 1800
    assert repo.git("rev-parse", "HEAD") == repo.base == pr["headRefOid"]
    assert repo.remote_head(lane) == repo.base
    assert repo.git("status", "--porcelain") == "M " + APP + "page.tsx"
    tags = repo.git("for-each-ref", "--format=%(refname)", "refs/tags/studio-checkpoint/")
    assert len(tags.splitlines()) == 2
    for tag in tags.splitlines():
        assert tag.startswith("refs/tags/studio-checkpoint/441-sales-xray-workspaces-")
        assert repo.git("rev-parse", tag + "^") == repo.base
    assert {repo.git("show", f"{t}:{APP}page.tsx") for t in tags.splitlines()} == {"one", "two"}
    assert not repo.git("ls-remote", "origin", "refs/tags/*")
    assert [(e["text"], e["pr"]) for e in repo.events("alert")] == [
        ("studio edits waiting: the ui checkout is on a lane PR branch", 17)
    ]
    assert not repo.events("review")
    assert not any("push" in c or c[:2] == ["gh", "api"] for c in repo.calls)


def test_lane_branch_commit_only_holds_without_github(repo):
    lane = "task/ui/441-sales-xray-workspaces"
    repo.branch(lane)
    repo.write(APP + "page.tsx", "edit")
    for _ in range(2):
        repo.tick(commit_only=True)
    assert repo.git("rev-parse", "HEAD") == repo.base
    tags = repo.git("for-each-ref", "--format=%(refname)", "refs/tags/studio-checkpoint/")
    assert len(tags.splitlines()) == 1
    assert repo.git("show", f"{tags}:{APP}page.tsx") == "edit"
    assert not any(c[0] == "gh" or "push" in c for c in repo.calls)
    assert not repo.events()


def test_hand_started_slice_never_requests_review(repo):
    repo.branch("task/ui/123-hand-started")
    repo.write(APP + "page.tsx", "edit")
    repo.tick()
    assert not repo.events("review")
    assert not any(c[:3] == ["gh", "pr", "create"] for c in repo.calls)
    assert repo.remote_head("task/ui/123-hand-started") == repo.git("rev-parse", "HEAD")


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
            repo.write(APP + "page.tsx", "sk-" + "F" * 24)
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


def test_next_dev_rewrite_of_next_env_is_neither_committed_nor_alerted(repo):
    repo.write("apps/sales-xray-web/next-env.d.ts", 'import "./.next/dev/types/routes.d.ts";')
    repo.write(APP + "page.tsx", "screen")
    repo.branch()
    repo.tick(True)
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "screen"
    assert "next-env.d.ts" not in repo.git("ls-tree", "-r", "--name-only", "HEAD")
    assert not repo.events("alert")


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
    payload = b"github_pat_" + b"F" * 30
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


@pytest.mark.parametrize("on_main", [False, True])
def test_css_token_substrings_are_committed(repo, on_main):
    if not on_main:
        repo.branch()
    css = ".task-card { mask-image: none; animation: ask-in 1s; } @keyframes ask-in {}"
    css += ".risk-" + "x" * 24 + " {} .are_you_sure_dialog_button_x {}"
    repo.write(APP + "screen.module.css", css)
    repo.tick()
    assert repo.git("show", "HEAD:" + APP + "screen.module.css") == css
    assert repo.git("branch", "--show-current").startswith(SYNC.STUDIO)
    assert not repo.git("status", "--porcelain")
    assert not repo.events("alert")


def advance_fixture_main(repo):
    branch = repo.git("branch", "--show-current")
    repo.git("switch", "main")
    repo.write("README.md", "other task on main")
    repo.git("add", "README.md")
    repo.git("commit", "-m", "other task")
    repo.git("push", "origin", "main")
    repo.git("switch", branch)


def approve_fixture(repo):
    repo.branch()
    repo.write(APP + "page.tsx", "approved screen")
    repo.tick()
    pr = repo.prs[0]
    repo.comments = [{"body": f"Merge approved: PR #17 @ {pr['headRefOid']}"}]
    return pr


def merge_fixture_pr(repo, pr):
    branch = repo.git("branch", "--show-current")
    repo.git("switch", "main")
    repo.git("merge", "--no-edit", pr["headRefOid"])
    repo.git("push", "origin", "main", f"{pr['headRefOid']}:refs/pull/17/head")
    repo.git("switch", branch)
    pr["state"] = "MERGED"


def test_carry_over_after_refresh_merges_main_during_approval_freeze(repo):
    pr = approve_fixture(repo)
    repo.write(PUBLIC + "before-refresh.svg", "local before refresh")
    repo.tick()
    advance_fixture_main(repo)
    repo.git("merge", "--no-edit", "origin/main")
    repo.write(APP + "page.tsx", "local after refresh")
    repo.tick()
    merge_fixture_pr(repo, pr)
    repo.tick()
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "local after refresh"
    assert repo.git("show", "HEAD:" + PUBLIC + "before-refresh.svg") == "local before refresh"
    assert repo.git("show", "HEAD:README.md") == "other task on main"
    assert repo.git("rev-list", "--count", "origin/main..HEAD") == "1"
    assert not repo.events("alert")


def test_watchdog_remote_update_defers_push_and_carries_local_commits(repo):
    pr = approve_fixture(repo)
    repo.write(PUBLIC + "waiting.svg", "unpublished")
    repo.tick()
    advance_fixture_main(repo)
    repo.git("switch", "-c", "watchdog-update", pr["headRefOid"])
    repo.git("merge", "--no-edit", "origin/main")
    remote = repo.git("rev-parse", "HEAD")
    repo.git("push", "origin", f"HEAD:refs/heads/{BRANCH}")
    pr["headRefOid"] = remote
    repo.git("switch", BRANCH)
    repo.write(APP + "page.tsx", "local after watchdog")
    repo.tick()
    assert repo.remote_head() == remote
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "local after watchdog"
    assert not repo.events("alert")
    repo.now += 7199
    repo.tick()
    assert not repo.events("alert")
    repo.now += 1
    repo.tick()
    assert len(repo.events("alert")) == 1
    assert repo.events("alert")[0]["key"] == "remote-ahead"
    first_alert = repo.events("alert")[0]["at"]
    repo.now += 1800
    repo.tick()
    assert repo.events("alert")[0]["at"] == first_alert
    merge_fixture_pr(repo, pr)
    repo.tick()
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "local after watchdog"
    assert repo.git("show", "HEAD:" + PUBLIC + "waiting.svg") == "unpublished"
    assert repo.git("show", "HEAD:README.md") == "other task on main"


def test_busy_reuses_archive_for_unchanged_head(repo):
    repo.busy = True
    repo.write(APP + "page.tsx", "checkpoint")
    repo.tick()
    first = repo.git("ls-remote", "--tags", "origin")
    repo.now += 1800
    repo.tick()
    repo.now += 1800
    repo.tick()
    assert repo.git("ls-remote", "--tags", "origin") == first
    repo.write(APP + "page.tsx", "new checkpoint")
    repo.now += 1800
    repo.tick()
    assert len(repo.git("ls-remote", "--tags", "origin").splitlines()) == 2


def test_carry_over_still_refuses_merge_from_another_branch(repo):
    pr = approve_fixture(repo)
    repo.git("switch", "-c", "unmerged-feature")
    repo.write(PUBLIC + "unreviewed.svg", "other branch")
    repo.git("add", PUBLIC + "unreviewed.svg")
    repo.git("commit", "-m", "unreviewed feature")
    repo.git("switch", BRANCH)
    repo.write(APP + "page.tsx", "local")
    repo.tick(True)
    repo.git("merge", "--no-edit", "unmerged-feature")
    merge_fixture_pr(repo, pr)
    with pytest.raises(SYNC.SyncError, match="merge"):
        repo.tick()
    assert not repo.git("tag")


@pytest.mark.parametrize(
    "token", FAKE_TOKENS, ids=["github", "github-pat", "sk", "aws", "pem", "cloudflare", "resend"]
)
def test_carry_over_rescans_shaped_tokens_before_archive(repo, token):
    # Deliberately synthetic history bypasses snapshot(), to exercise the second scan.
    repo.write(APP + "fixture.txt", token)
    repo.git("add", APP + "fixture.txt")
    repo.git("commit", "-m", "synthetic refused history")
    repo.write(APP + "page.tsx", "safe screen edit")
    with pytest.raises(SYNC.SyncError, match="refused content"):
        repo.tick()
    assert not repo.git("ls-remote", "--tags", "origin")
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "safe screen edit"


@pytest.mark.parametrize("conflict", [False, True])
def test_carry_over_refuses_hand_edited_refresh_merge_before_archive(repo, conflict):
    pr = approve_fixture(repo)
    if conflict:
        repo.write(PUBLIC + "old.svg", "local conflict")
        repo.git("add", PUBLIC + "old.svg")
        repo.git("commit", "-m", "local conflict")
    advance_fixture_main(repo)
    if conflict:
        repo.git("switch", "main")
        repo.write(PUBLIC + "old.svg", "main conflict")
        repo.git("add", PUBLIC + "old.svg")
        repo.git("commit", "-m", "main conflict")
        repo.git("push", "origin", "main")
        repo.git("switch", BRANCH)
        with pytest.raises(SYNC.SyncError):
            repo.git("merge", "--no-commit", "origin/main")
        repo.write(PUBLIC + "old.svg", "manually resolved")
        repo.git("add", PUBLIC + "old.svg")
    else:
        repo.git("merge", "--no-commit", "origin/main")
    repo.write(APP + "evil.txt", "re_" + "F" * 24)
    repo.git("add", APP + "evil.txt")
    repo.git("commit", "-m", "synthetic doctored refresh")
    repo.write(APP + "page.tsx", "after refresh")
    repo.tick()
    merge_fixture_pr(repo, pr)
    with pytest.raises(SYNC.SyncError, match="Carry-over contains a merge"):
        repo.tick()
    assert not repo.git("ls-remote", "--tags", "origin")


@pytest.mark.parametrize("refresh", [False, True])
def test_merged_pr_without_carry_over_releases_lane(repo, refresh):
    pr = approve_fixture(repo)
    if refresh:
        advance_fixture_main(repo)
        repo.git("merge", "--no-edit", "origin/main")
    merge_fixture_pr(repo, pr)
    repo.git("push", "origin", "--delete", BRANCH)
    repo.calls.clear()
    repo.tick()
    assert repo.git("branch", "--show-current") == "main"
    assert repo.git("rev-parse", "HEAD") == repo.remote_head("main")
    assert not repo.git("ls-remote", "origin", "refs/heads/task/ui/*", "refs/tags/*")
    assert not any(c[:3] == ["gh", "pr", "create"] for c in repo.calls)
    assert not any(c[:3] == [sys.executable, "scripts/ac_task.py", "start"] for c in repo.calls)
    assert "pending" not in json.loads(repo.state.read_text())
    assert not repo.events("alert")


def test_empty_carry_over_retries_done_without_claiming_lane(repo):
    pr = approve_fixture(repo)
    merge_fixture_pr(repo, pr)
    repo.git("push", "origin", "--delete", BRANCH)
    repo.done_busy = True
    repo.tick()
    assert repo.git("branch", "--show-current") == BRANCH
    assert not repo.events("alert")
    repo.now += 7200
    repo.tick()
    assert [e["key"] for e in repo.events("alert")] == ["gate-busy"]
    repo.done_busy = False
    repo.tick()
    assert repo.git("branch", "--show-current") == "main"
    assert not repo.git("ls-remote", "origin", "refs/heads/task/ui/*", "refs/tags/*")
    assert "pending" not in json.loads(repo.state.read_text())


def test_main_with_only_refused_files_does_not_claim_lane(repo):
    repo.write(APP + "fixture.txt", "re_" + "F" * 24)
    repo.tick()
    assert repo.git("branch", "--show-current") == "main"
    assert repo.git("rev-parse", "HEAD") == repo.base
    assert not repo.git("ls-remote", "origin", "refs/heads/task/ui/*", "refs/tags/*")
    assert "pending" not in json.loads(repo.state.read_text())
    assert [e["key"] for e in repo.events("alert")] == ["refused-file"]


@pytest.mark.parametrize("field", ["message", "author", "committer"])
def test_carry_over_scans_commit_metadata_before_any_archive(repo, field):
    token = FAKE_TOKENS[0]
    repo.write(APP + "page.tsx", "safe content")
    repo.git("add", APP + "page.tsx")
    env = {f"GIT_{field.upper()}_NAME": token} if field != "message" else {}
    SYNC.command(
        ["git", "commit", "-m", token if field == "message" else "safe message"],
        cwd=repo.repo,
        env=env,
    )
    # Even metadata in an earlier commit must be scanned.
    repo.write(APP + "page.tsx", "next safe content")
    with pytest.raises(SYNC.SyncError, match="Carry-over contains refused content"):
        repo.tick()
    assert not repo.git("tag")
    assert not repo.git("ls-remote", "--tags", "origin")
    assert not any("start" in c for c in repo.calls)


@pytest.mark.parametrize("claimed", [False, True])
@pytest.mark.parametrize("parallel_lane", [None, "task/platform/999-other"])
def test_partial_gate_start_retries_from_target_without_losing_checkpoint(
    repo, claimed, parallel_lane
):
    repo.write(APP + "page.tsx", "saved before partial start")
    original = repo.runner

    def partial_start(argv, **kwargs):
        if argv[:3] == [sys.executable, "scripts/ac_task.py", "start"]:
            if claimed:
                original(argv, **kwargs)
            else:
                repo.git("switch", "-c", "task/ui/" + argv[-1], "origin/main")
            raise SYNC.SyncError("start interrupted after switching")
        return original(argv, **kwargs)

    repo.runner = partial_start
    repo.tick()
    pending = json.loads(repo.state.read_text())["pending"]
    assert repo.git("branch", "--show-current") == pending["target"]
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "original"
    assert (
        repo.git("show", pending["archive"] + ":" + APP + "page.tsx")
        == "saved before partial start"
    )
    repo.runner = original
    if parallel_lane:
        repo.git("push", "origin", f"HEAD:refs/heads/{parallel_lane}")
    repo.tick()
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "saved before partial start"
    assert repo.remote_head(pending["target"]) == repo.git("rev-parse", "HEAD")
    assert repo.git("rev-parse", "main") == repo.base
    assert "pending" not in json.loads(repo.state.read_text())
    assert not repo.git("status", "--porcelain")
    assert not repo.events("alert")
    assert any(c[:3] == ["gh", "pr", "create"] for c in repo.calls)


@pytest.mark.parametrize("claim", ["task/ui/999-other", "task/999-exclusive", "task/unknown/999"])
def test_partial_gate_start_waits_for_competing_claim_before_push_or_replay(repo, claim):
    repo.write(APP + "page.tsx", "saved before partial start")
    original = repo.runner

    def partial_start(argv, **kwargs):
        if argv[:3] == [sys.executable, "scripts/ac_task.py", "start"]:
            repo.git("switch", "-c", "task/ui/" + argv[-1], "origin/main")
            raise SYNC.SyncError("start interrupted after switching")
        return original(argv, **kwargs)

    repo.runner = partial_start
    repo.tick()
    pending = json.loads(repo.state.read_text())["pending"]
    repo.runner = original
    repo.git("push", "origin", f"HEAD:refs/heads/{claim}")
    repo.calls.clear()
    repo.tick()
    assert json.loads(repo.state.read_text())["pending"] == pending
    assert not repo.events("alert")
    repo.now += 7200
    repo.tick()
    first_alert = repo.events("alert")
    assert [e["key"] for e in first_alert] == ["gate-busy"]
    repo.now += 1800
    repo.tick()
    assert repo.events("alert") == first_alert
    assert not any("push" in c or "cherry-pick" in c for c in repo.calls)
    assert not any(c[:3] == ["gh", "pr", "create"] for c in repo.calls)
    assert not repo.git("ls-remote", "--heads", "origin", pending["target"])
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "original"
    assert repo.git("rev-parse", "HEAD") == repo.base
    assert not json.loads(repo.state.read_text())["pending"].get("replaying")
    assert (
        repo.git("show", pending["archive"] + ":" + APP + "page.tsx")
        == "saved before partial start"
    )
    repo.git("push", "origin", "--delete", claim)
    repo.tick()
    assert "pending" not in json.loads(repo.state.read_text())
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "saved before partial start"
    assert repo.remote_head(pending["target"]) == repo.git("rev-parse", "HEAD")


@pytest.mark.parametrize("on_main", [False, True])
@pytest.mark.parametrize("advance_main", [False, True])
def test_net_zero_carry_over_does_not_archive_or_claim_lane(repo, on_main, advance_main):
    if not on_main:
        pr = approve_fixture(repo)
        original = "approved screen"
    else:
        original = "original\n"
    repo.write(APP + "page.tsx", "temporary edit")
    repo.tick(True)
    repo.write(APP + "page.tsx", original)
    repo.tick(True)
    if not on_main:
        merge_fixture_pr(repo, pr)
        repo.git("push", "origin", "--delete", BRANCH)
    if advance_main:
        repo.git("switch", "-c", "other-task", "origin/main")
        repo.write("README.md", "new main content")
        repo.git("add", "README.md")
        repo.git("commit", "-m", "advance main")
        repo.git("push", "origin", "HEAD:main")
        repo.git("switch", "main" if on_main else BRANCH)
    repo.calls.clear()
    repo.tick()
    assert repo.git("branch", "--show-current") == "main"
    assert repo.git("rev-parse", "HEAD") == repo.remote_head("main")
    assert not repo.git("tag")
    assert not repo.git("ls-remote", "origin", "refs/heads/task/ui/*", "refs/tags/*")
    assert not any(c[:3] == ["gh", "pr", "create"] for c in repo.calls)
    assert not any(c[:3] == [sys.executable, "scripts/ac_task.py", "start"] for c in repo.calls)
    assert "pending" not in json.loads(repo.state.read_text())
    assert not repo.events("alert")


@pytest.mark.parametrize("broken", [b'{"pending":', b'{"text":"\xe2\x82', b"[]", b"null"])
def test_malformed_state_cli_moves_aside_alerts_once_and_completes(repo, monkeypatch, broken):
    from types import SimpleNamespace

    monkeypatch.setattr(SYNC.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(SYNC.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_name="acdev"))
    repo.branch()
    repo.state.write_bytes(broken)
    repo.write(APP + "page.tsx", "save despite broken state")
    args = [
        "--repo",
        str(repo.repo),
        "--state",
        str(repo.state),
        "--spool",
        str(repo.spool),
        "--lock",
        str(repo.repo.parent / "state.lock"),
        "--commit-only",
    ]
    assert SYNC.main(args) == 0
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "save despite broken state"
    backups = list(repo.state.parent.glob("state.json.bad-*"))
    assert len(backups) == 1 and backups[0].read_bytes() == broken
    assert json.loads(repo.state.read_text()) == {}
    assert [e["key"] for e in repo.events("alert")] == ["bad-state"]
    first_alert = repo.events("alert")[0]
    assert SYNC.main(args) == 0
    assert repo.events("alert") == [first_alert]


def test_service_runtime_lock_environment_and_sandbox():
    service = configparser.ConfigParser(interpolation=None)
    service.read(SCRIPT.with_suffix(".service"))
    values = service["Service"]
    assert values["User"] == "acdev"
    assert values["RuntimeDirectory"] == "ac-studio-sync"
    assert values["RuntimeDirectoryPreserve"] == "yes"
    assert SYNC.LOCK.parent == Path("/run") / values["RuntimeDirectory"]
    assert str(SYNC.LOCK.parent) in values["ReadWritePaths"].split()
    assert "/run/user" not in SCRIPT.with_suffix(".service").read_text()
    assert set(values["Environment"].split()) == {
        "PATH=/home/acdev/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "GH_NO_UPDATE_NOTIFIER=1",
        "GH_PROMPT_DISABLED=1",
    }
    assert values["TasksMax"] == "32"
    assert values["NoNewPrivileges"] == values["PrivateTmp"] == "true"
    assert values["ProtectSystem"] == "strict"
    assert values["ProtectHome"] == "read-only"


def test_fictional_json_fixtures_allowed_in_commit_and_carry_over(repo):
    path = "apps/sales-xray-web/tests/fixtures/fictional-call.json"
    repo.write(path, '{"fictional": true}')
    repo.tick()
    assert repo.git("show", "HEAD:" + path) == '{"fictional": true}'
    assert repo.git("branch", "--show-current").startswith(SYNC.STUDIO)
    assert not repo.events("alert")


@pytest.mark.parametrize(
    "path",
    [
        "apps/sales-xray-web/tests/fixtures/nested/call.json",
        "apps/sales-xray-web/tests/fixtures/call.ts",
        "apps/sales-xray-web/tests/fixtures-other/call.json",
        "apps/sales-xray-web/tests/call.json",
    ],
)
def test_fixture_allowlist_does_not_include_adjacent_paths(repo, path):
    repo.branch()
    repo.write(path, "unrelated")
    repo.tick(True)
    assert path not in repo.git("ls-tree", "-r", "--name-only", "HEAD")
    assert [e["key"] for e in repo.events("alert")] == ["outside-allowlist"]


def test_parked_carry_over_is_not_mistaken_for_net_zero_on_retry(repo):
    pr = approve_fixture(repo)
    repo.write(APP + "page.tsx", "unpublished after approval")
    repo.tick(True)
    merge_fixture_pr(repo, pr)
    repo.git("push", "origin", "--delete", BRANCH)
    repo.busy = True
    repo.tick()
    assert repo.git("branch", "--show-current") == "main"
    repo.tick()
    assert json.loads(repo.state.read_text())["pending"]["commits"]
    repo.busy = False
    repo.tick()
    assert repo.git("show", "HEAD:" + APP + "page.tsx") == "unpublished after approval"
    assert not repo.events("alert")
