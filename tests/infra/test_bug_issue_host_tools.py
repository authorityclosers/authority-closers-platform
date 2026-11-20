"""v0.93 host tools: the release timer pairs each "live on production" line with the hold line
before it, and the Pulse alert's task carries the screen, count and link, never words."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

SCRIPTS = Path(__file__).resolve().parents[2] / "infra/application/scripts"


def load(name: str) -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(SCRIPTS / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_each_live_release_takes_the_hold_line_before_it() -> None:
    release = load("ac-bugs-release")
    lines = [
        "2026-10-25T08:55:03Z hold 6815dc2b2c79b18af0be145df3972a9bbf932f86"
        " (workbench 2e1970d86 over main 153b1aa2e)",
        "2026-10-25T10:24:57Z v0.90.0 is live on production and its canary passed: https://x",
        "2026-10-25T10:24:57Z v0.90.0 is live on production and its canary passed: https://x",
        "2026-10-25T15:00:05Z hold c197101f1d68afa0e280ded1c39758b5979c3a6b"
        " (workbench 3ba4464ba over main d279b04ad)",
        "2026-10-25T16:00:00Z something else",
        "2026-10-25T16:38:38Z v0.91.0 is live on production and its canary passed: https://x",
    ]
    assert release.releases(lines) == [
        ("v0.90.0", "2e1970d86", ()),
        ("v0.91.0", "3ba4464ba", ()),
    ]
    assert release.releases(["2026-10-25T16:38:38Z v0.91.0 is live on production"]) == []


def test_a_cutlist_release_takes_its_hold_and_the_commits_its_cut_listed() -> None:
    # Bug audit, 20 Nov 2026: since 29 Oct cutlist.sh logs "hold <sha> over main <sha>",
    # which the hook didn't read, so every release from v1.3 on was paired with the last
    # old-style hold and nothing was marked solved after v1.33.
    release = load("ac-bugs-release")
    lines = [
        "2026-10-28T17:22:22Z hold f711af94c0b33f0877c32a88c1d58814cf16a166"
        " (workbench ba06ff909 over main 4a6564b53)",
        "2026-10-28T18:00:00Z v1.2.0 is live on production and its canary passed: https://x",
        "2026-11-20T04:45:19Z === cut v1.89.0 over main b44069724"
        " (orchestrator; commits: 12873bf46 2a3fa35a3)",
        "2026-11-20T04:45:21Z hold 9503bffe85e355409d01dfa08730663895fcf65b over main b44069724",
        "2026-11-20T06:45:37Z === cut v1.89.0 over main b44069724"
        " (orchestrator; commits: bbf7e60ee 3584f6b8f)",
        "2026-11-20T06:45:39Z hold 71f168d0497e147ee7508d489f7e0f1a319e8c1a over main b44069724",
        "2026-11-20T07:02:13Z wb-ci --full green on hold 71f168d04 (attempt 1)",
        "2026-11-20T08:10:26Z v1.89.0 is live on production and its canary passed: https://x",
        "2026-11-20T09:00:00Z v1.89.0 is live on production again after a rollback",
    ]
    assert release.releases(lines) == [
        ("v1.2.0", "ba06ff909", ()),
        ("v1.89.0", "71f168d0497e147ee7508d489f7e0f1a319e8c1a", ("bbf7e60ee", "3584f6b8f")),
    ]


def test_a_release_carries_a_listed_commit_rebuilt_onto_main(tmp_path: Path) -> None:
    # A cutlist hold is main plus only the listed commits' files, often rebuilt onto main
    # first: the fix's own sha is neither in the hold's history nor in the list.
    bugs = load("ac-bugs")
    repo = str(tmp_path)

    def git(*args: str) -> str:
        return subprocess.run(  # noqa: S603 - fixed argv
            ["git", "-C", repo, *args],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "fictional@example.com")
    git("config", "user.name", "Fictional")
    (tmp_path / "a.txt").write_text("one\n")
    git("add", "a.txt")
    git("commit", "-q", "-m", "Start")
    git("checkout", "-q", "-b", "workbench")
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    subject = "Leads: a fictional fix for a fictional bug report, long enough to name it"
    git("commit", "-qam", subject)
    fix = git("rev-parse", "HEAD")
    (tmp_path / "b.txt").write_text("other\n")
    git("add", "b.txt")
    git("commit", "-q", "-m", "Another change on the workbench, not in the release at all")
    other = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    (tmp_path / "c.txt").write_text("main moved on\n")
    git("add", "c.txt")
    git("commit", "-q", "-m", "Main moved on")
    git("cherry-pick", fix)
    rebuilt = git("rev-parse", "HEAD")
    hold = git("commit-tree", git("rev-parse", "HEAD^{tree}"), "-p", "HEAD", "-m", "Hold")

    assert rebuilt != fix
    assert bugs.carried(repo, fix, [hold], [rebuilt])
    assert bugs.carried(repo, fix, [fix], [])
    assert not bugs.carried(repo, other, [hold], [rebuilt])
    assert not bugs.carried(repo, fix, [hold], [])
    assert not bugs.carried(repo, "8fed556", [hold], [rebuilt])


def test_a_pulse_task_names_the_screen_and_count_never_the_words() -> None:
    alerts = load("ac-bug-alerts")
    title, notes = alerts.task_text(
        "production",
        {
            "id": "6d1c2a1e-3b4d-4c5e-8f6a-7b8c9d0e1f2a",
            "number": 4,
            "screen": "/leads",
            "area": "leads",
            "status": "new",
            "count": 3,
            "came_back": True,
            "first_seen": "2026-10-25T13:15:00+00:00",
            "last_seen": "2026-10-26T04:30:00+00:00",
            "orgs": 1,
            "devices": {"CPH2793": 2, "IV2201": 1},
            "android": {"Android 16": 2},
        },
    )
    assert title == "Bug 4: /leads · 3 reports · came back after the fix"
    assert "https://admin.authorityclosers.com/bugs?issue=4" in notes
    assert "Marker: bug:6d1c2a1e-3b4d-4c5e-8f6a-7b8c9d0e1f2a" in notes
    # Only the screen, the count and the Admin link (orchestrator, 26 Oct 2026).
    assert notes.splitlines()[:3] == [
        "Screen: /leads",
        "Reports: 3",
        "Admin: https://admin.authorityclosers.com/bugs?issue=4",
    ]
    for absent in ("CPH2793", "Android", "organisation", "2026-10"):
        assert absent not in notes
