#!/usr/bin/env python3
"""Preserve studio edits; run as acdev. R1 installs the units and drains the spool.

Approval transport: GitHub PR conversation comments (the PR's issue), or
state.json approvals["<PR number>"] = "<approved SHA>" supplied by the watchdog.
An approval freezes the published head even while further local commits accrue.
All invocations, including --commit-only, acquire the same flock internally;
callers must not acquire that lock a second time around this process.
"""

from __future__ import annotations

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import pwd
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

PREFIXES = ("apps/sales-xray-web/app/", "apps/sales-xray-web/public/")
STUDIO = "task/ui/296-studio-"
TOKENS = (b"ghp_", b"github_pat_", b"sk-", b"AKIA", b"-----BEGIN")
LIMIT = 1024 * 1024
IDENTITY = {
    "GIT_AUTHOR_NAME": "UI Studio",
    "GIT_AUTHOR_EMAIL": "studio@paperclip.ing",
    "GIT_COMMITTER_NAME": "UI Studio",
    "GIT_COMMITTER_EMAIL": "studio@paperclip.ing",
}


class SyncError(Exception):
    """Only static, non-sensitive messages may cross the event boundary."""


def command(argv, *, cwd, env=None):
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell; paths are literal
        argv, cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, timeout=45
    )
    if result.returncode:
        raise SyncError(f"{Path(argv[0]).name} failed (exit {result.returncode}); inspect locally")
    return result.stdout.decode("utf-8", errors="surrogateescape")


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def stamp(value):
    return datetime.fromtimestamp(value, UTC).isoformat()


class Sync:
    def __init__(self, repo, state, spool, *, runner=command, now=None):
        self.repo, self.state_path, self.spool = Path(repo), Path(state), Path(spool)
        self.runner, self.now = runner, time.time() if now is None else now
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}

    def run(self, *args, env=None):
        return self.runner(list(args), cwd=self.repo, env=env)

    def git(self, *args, env=None):
        return self.run("git", "--literal-pathspecs", *args, env=env)

    def save(self):
        atomic_json(self.state_path, self.state)

    def event(self, kind, key, text, pr=None):
        event = {"kind": kind, "key": key, "at": stamp(self.now), "text": text}
        if pr is not None:
            event["pr"] = pr
        name = hashlib.sha256(f"{kind}:{key}".encode()).hexdigest() + ".json"
        atomic_json(self.spool / name, event)

    def branch(self):
        return self.git("rev-parse", "--abbrev-ref", "HEAD").strip()

    def head(self):
        return self.git("rev-parse", "HEAD").strip()

    def paths(self):
        changed = self.git("diff", "--name-only", "--no-renames", "-z", "HEAD")
        staged = self.git("diff", "--cached", "--name-only", "--no-renames", "-z")
        untracked = self.git("ls-files", "--others", "--exclude-standard", "-z")
        paths = sorted(set((changed + staged + untracked).split("\0")) - {""})
        if any(not p.startswith(PREFIXES) for p in paths):
            self.event("alert", "outside-allowlist", "Non-screen edits remain uncommitted.")
        return [p for p in paths if p.startswith(PREFIXES)]

    def safe_name(self, path):
        return not any(
            fnmatch.fnmatch(part, pattern)
            for part in Path(path).parts
            for pattern in (".env*", "*.pem", "*.key", "id_*")
        )

    def commit(self, paths):
        """A separate index captures and scans the exact blobs that will be committed."""
        accepted = []
        for path in paths:
            full = self.repo / path
            if (
                not self.safe_name(path)
                or full.is_symlink()
                or any(p.is_symlink() for p in full.parents if p != self.repo.parent)
                or (full.exists() and (not full.is_file() or full.stat().st_size > LIMIT))
            ):
                self.event(
                    "alert",
                    "refused-path",
                    "Skipped a sensitive, non-regular or oversized screen file.",
                )
            else:
                accepted.append(path)
        if not accepted:
            return False
        for key, value in (("user.name", "UI Studio"), ("user.email", "studio@paperclip.ing")):
            try:
                self.git("config", "--get", key)
            except SyncError:
                self.git("config", "--local", key, value)
        with tempfile.TemporaryDirectory(prefix="ac-studio-index-") as directory:
            env = {**IDENTITY, "GIT_INDEX_FILE": str(Path(directory) / "index")}
            self.git("read-tree", "HEAD", env=env)
            self.git("add", "-A", "--", *accepted, env=env)
            staged = self.git("diff", "--cached", "--name-only", "--no-renames", "-z", env=env)
            entries = self.git("ls-files", "--stage", "-z", env=env)
            blobs = {
                row.split("\t", 1)[1]: row.split("\t", 1)[0].split()[:2]
                for row in entries.split("\0")
                if row
            }
            for path in staged.split("\0"):
                if path and path in blobs:
                    mode, oid = blobs[path]
                    size = int(self.git("cat-file", "-s", oid))
                    blob = (
                        self.git("cat-file", "blob", oid).encode("utf-8", "surrogateescape")
                        if size <= LIMIT
                        else b""
                    )
                    if (
                        mode not in ("100644", "100755")
                        or size > LIMIT
                        or any(token in blob for token in TOKENS)
                    ):
                        self.git("reset", "-q", "HEAD", "--", path, env=env)
                        self.event(
                            "alert",
                            "refused-content",
                            "Skipped a screen file containing a token marker or over 1 MiB.",
                        )
            included = self.git("diff", "--cached", "--name-only", "--no-renames", "-z", env=env)
            if not included:
                return False
            # Disable hooks: the committed tree must remain exactly the scanned tree.
            self.git(
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgSign=false",
                "commit",
                "-m",
                "Save UI Studio edits\n\nCo-Authored-By: Paperclip <noreply@paperclip.ing>",
                env=env,
            )
            self.git("reset", "-q", "HEAD", "--", *included.rstrip("\0").split("\0"))
        return True

    def pr(self, branch):
        items = json.loads(
            self.run(
                "gh",
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                "all",
                "--json",
                "number,state,headRefOid,createdAt",
            )
        )
        return max(items, key=lambda item: item["number"]) if items else None

    def approved(self, pr):
        sha = pr["headRefOid"]
        cached = self.state.get("approvals", {}).get(str(pr["number"]), "")
        if re.fullmatch(r"[0-9a-f]{7,40}", cached) and sha.startswith(cached):
            return True
        pages = json.loads(
            self.run(
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"repos/{{owner}}/{{repo}}/issues/{pr['number']}/comments",
            )
        )
        pattern = rf"^(?:Merge|UI Guard) approved: PR #{pr['number']} @ ([0-9a-f]{{7,40}})\s*$"
        return any(
            sha.startswith(match)
            for page in pages
            for comment in page
            for match in re.findall(pattern, comment.get("body", ""), re.MULTILINE)
        )

    def checkpoint(self, base, source):
        self.state["pending"] = {
            "base": base,
            "source": source,
            "target": STUDIO + datetime.fromtimestamp(self.now, UTC).strftime("%Y%m%d%H%M"),
            "since": self.now,
        }
        self.save()

    def transfer(self):
        pending = self.state["pending"]
        if pending.get("replaying"):
            raise SyncError(
                "Interrupted replay needs local recovery; archive and checkout are preserved"
            )
        head = self.head()
        base = pending.get("main_base", pending["base"])
        commits = (
            pending.get("commits", [])
            + self.git("rev-list", "--reverse", f"{base}..{head}").split()
        )
        # Do not archive unsafe history introduced manually between ticks.
        for commit in commits:
            if len(self.git("rev-list", "--parents", "-n", "1", commit).split()) != 2:
                raise SyncError("Carry-over contains a merge; local history preserved for review")
            paths = self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "-z", commit)
            for path in filter(None, paths.split("\0")):
                if not path.startswith(PREFIXES) or not self.safe_name(path):
                    raise SyncError("Carry-over contains a refused path; local history preserved")
                entry = self.git("ls-tree", commit, "--", path)
                if entry:
                    mode, _, oid = entry.split("\t", 1)[0].split()
                    size = int(self.git("cat-file", "-s", oid))
                    if mode not in ("100644", "100755") or size > LIMIT:
                        raise SyncError(
                            "Carry-over contains refused content; local history preserved"
                        )
                    blob = self.git("cat-file", "blob", oid).encode("utf-8", "surrogateescape")
                    if any(token in blob for token in TOKENS):
                        raise SyncError(
                            "Carry-over contains refused content; local history preserved"
                        )
        tag = f"archive/studio-{int(self.now)}-{head[:12]}"
        if not self.git("tag", "--list", tag).strip():
            self.git("tag", tag, head)
        elif self.git("rev-parse", tag).strip() != head:
            raise SyncError("Archive tag collision; existing history preserved")
        self.git("push", "origin", f"refs/tags/{tag}")
        pending.update(archive=tag, commits=commits, main_base=head)
        self.save()
        try:
            if self.branch() != "main":
                self.run(sys.executable, "scripts/ac_task.py", "done")
                pending.update(parked=True, main_base=self.head())
                self.save()
            self.run(
                sys.executable,
                "scripts/ac_task.py",
                "start",
                "ui",
                pending["target"].removeprefix("task/ui/"),
            )
        except SyncError:
            pending.setdefault("busy_since", self.now)
            if self.now - pending["busy_since"] >= 7200 and not pending.get("alerted"):
                self.event(
                    "alert",
                    "gate-busy",
                    "Studio gate blocked for at least two hours; checkpoint archived.",
                )
                pending["alerted"] = True
            self.save()
            return False
        # The checkpoint is archived; align local main using an expected-old guard.
        self.git(
            "update-ref",
            "refs/heads/main",
            self.git("rev-parse", "origin/main").strip(),
            pending["main_base"],
        )
        if commits:
            pending["replaying"] = True
            self.save()
            self.git("cherry-pick", "--no-commit", *commits)
            self.git("reset", "-q")
            self.commit(self.paths())
        del self.state["pending"]
        self.save()
        return True

    def publish(self, branch, pr):
        if pr and pr["state"] == "CLOSED":
            raise SyncError("Closed PR requires local review before publishing again")
        if pr and self.approved(pr):
            return
        head = self.head()
        self.git("push", "--set-upstream", "origin", branch)
        if not pr:
            if not self.git("diff", "--name-only", "origin/main...HEAD").strip():
                return
            body = (
                "Task: AUT-296\n\nAutomatically preserved studio screen edits.\n\n"
                "Approval freeze reads SHA-bound Merge approved / UI Guard approved lines "
                "on this GitHub PR conversation, or state.json approvals[PR number] written "
                "by the watchdog. Local commits continue while that published head is approved.\n"
                "UI Guard reviews only studio slices under ADR 0041; "
                "CI and review remain required."
            )
            self.run(
                "gh",
                "pr",
                "create",
                "--base",
                "main",
                "--head",
                branch,
                "--title",
                "UI Studio saved screen edits",
                "--body",
                body,
            )
            pr = self.pr(branch)
        if not pr or not branch.startswith(STUDIO):
            return
        key = str(pr["number"])
        pacing = self.state.setdefault("prs", {}).setdefault(key, {})
        if pacing.get("head") != head:
            pacing.update(head=head, unchanged_since=self.now)
        created = datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00")).timestamp()
        eligible = self.now - pacing["unchanged_since"] >= 1800 or self.now - created >= 7200
        if eligible and self.now - pacing.get("review_at", float("-inf")) >= 7200:
            self.event(
                "review",
                f"pr-{key}-{int(self.now // 7200)}",
                f"Review studio PR #{key} at {head} under ADR 0041.",
                pr["number"],
            )
            pacing["review_at"] = self.now
        self.save()

    def tick(self, commit_only=False):
        branch = self.branch()
        gitdir = Path(self.git("rev-parse", "--absolute-git-dir").strip())
        if (branch != "main" and not branch.startswith("task/ui/")) or any(
            (gitdir / name).exists()
            for name in (
                "MERGE_HEAD",
                "REBASE_HEAD",
                "CHERRY_PICK_HEAD",
                "rebase-merge",
                "rebase-apply",
                "sequencer",
            )
        ):
            raise SyncError("Unsupported branch or unfinished Git operation; no Git writes")
        paths = self.paths()
        if branch == "main" and any(
            self.now
            - ((self.repo / p) if (self.repo / p).exists() else (self.repo / p).parent)
            .lstat()
            .st_mtime
            < 120
            for p in paths
        ):
            return
        pending = self.state.get("pending")
        if pending and (
            (pending["source"] != branch and not (pending.get("parked") and branch == "main"))
            or pending.get("replaying")
        ):
            raise SyncError("Interrupted slice transition needs local recovery; archive preserved")
        # --commit-only has no gh calls, pushes, or branch transitions.
        if branch == "main" and not pending and paths:
            self.checkpoint(self.git("rev-parse", "origin/main").strip(), branch)
        self.commit(paths)
        if commit_only:
            return
        pr = None if branch == "main" or pending else self.pr(branch)
        if pr and pr["state"] == "MERGED":
            self.git("fetch", "origin", f"refs/pull/{pr['number']}/head")
            self.checkpoint(pr["headRefOid"], branch)
        if self.state.get("pending"):
            if not self.transfer():
                return
            branch, pr = self.branch(), None
        if branch != "main":
            self.publish(branch, pr)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path("/home/acdev/src/lanes/ui/authority-closers-platform")
    )
    parser.add_argument(
        "--state", type=Path, default=Path.home() / ".local/state/ac-studio-sync/state.json"
    )
    parser.add_argument("--spool", type=Path, default=Path("/var/lib/ac-studio/notify"))
    parser.add_argument(
        "--lock", type=Path, default=Path(f"/run/user/{os.getuid()}/ac-studio-sync.lock")
    )
    parser.add_argument("--commit-only", action="store_true")
    args = parser.parse_args(argv)
    if os.geteuid() == 0 or pwd.getpwuid(os.geteuid()).pw_name != "acdev":
        parser.error("ac-studio-sync must run as acdev, never root")
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        sync = Sync(args.repo, args.state, args.spool)
        try:
            sync.tick(args.commit_only)
        except (SyncError, OSError, ValueError, subprocess.TimeoutExpired) as error:
            text = (
                str(error)
                if isinstance(error, SyncError)
                else "Studio sync failed; inspect locally."
            )
            sync.event("alert", "sync-error", text)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
