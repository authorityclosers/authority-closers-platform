"""A release that changes no web input keeps the running web image (the orchestrator, 15 Nov 2026:
three releases that changed no web file stopped at staging, waiting for a web build that the web
workflow's path filter never starts). The inputs are the filter itself, read at the target."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.infra.test_ac_release import (
    HEAD,
    MODULE,
    OLD,
    FakeGitHub,
    FakeRunner,
    make_engine,
    ready_core,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = """name: Sales Xray web image
on:
  push:
    branches:
      - main
    paths:
      - .dockerignore
      - apps/sales-xray-web/**
      - infra/sales-xray-web/**  # the image recipe
      - packages/typescript/**
      - package.json
  workflow_dispatch:
    inputs:
      paths:
        description: not a filter
"""
FILTER = [
    ".dockerignore",
    "apps/sales-xray-web/**",
    "infra/sales-xray-web/**",
    "packages/typescript/**",
    "package.json",
]


class FilesRunner(FakeRunner):
    """FakeRunner plus the two git reads the web check makes."""

    def __init__(self, changed: list[str], workflow: str = WORKFLOW) -> None:
        super().__init__()
        self.changed = changed
        self.workflow = workflow

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        argv = list(argv)
        if argv[:1] == ["git"] and "show" in argv:
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, self.workflow, "")
        if argv[:1] == ["git"] and "diff" in argv:
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "\n".join(self.changed) + "\n", "")
        return super().__call__(argv, **kwargs)


def staging(tmp_path: Path, runner: FilesRunner, *, running: str = OLD):
    github = FakeGitHub()
    ready_core(github, HEAD)  # main built no web image for HEAD
    runner.web_image = "sha256:" + "e" * 64
    runner.image_marker[runner.web_image] = running
    engine = make_engine(tmp_path, github, runner)
    engine.deploy_web = lambda *a, **k: pytest.fail("there is no web build to deploy")
    return engine


def test_the_web_inputs_are_the_workflows_own_path_filter() -> None:
    assert MODULE.web_path_filter(WORKFLOW) == FILTER
    # A filter this can't read whole gives no list: the web counts as changed.
    assert MODULE.web_path_filter(WORKFLOW.replace("- package.json", "- '!package.json'")) == []
    assert MODULE.web_path_filter(WORKFLOW.replace("    paths:", "    paths-ignore:", 1)) == []
    real = MODULE.web_path_filter(
        (ROOT / ".github/workflows" / MODULE.WEB_WORKFLOW).read_text(encoding="utf-8")
    )
    assert "apps/sales-xray-web/**" in real and "infra/sales-xray-web/**" in real
    changed = MODULE.web_input_changed
    assert changed(["apps/sales-xray-web/app/page.tsx"], FILTER)
    assert changed(["infra/sales-xray-web/Dockerfile"], FILTER)
    assert changed(["package.json"], FILTER)
    assert not changed(["apps/admin-web/package.json"], FILTER)
    assert not changed(["packages/python/ac_platform/x.py", "docs/a.md", ""], FILTER)
    assert changed(["a/b/c.md"], ["**/c.md"]) and changed(["c.md"], ["**/c.md"])


def test_a_release_with_no_web_change_keeps_the_running_web_image(tmp_path: Path) -> None:
    runner = FilesRunner(["packages/python/ac_platform/x.py", "tests/unit/test_x.py"])
    runner.ancestors.add((OLD, HEAD))
    engine = staging(tmp_path, runner)
    results = engine.deploy("staging", HEAD, "web", dry_run=False)
    assert [(item["result"], item["sha"]) for item in results] == [("kept", OLD)]
    assert results[0]["detail"] == (
        f"web inputs unchanged since {OLD[:12]}: keeping that web image for {HEAD[:12]}"
    )
    shown = [call for call in runner.calls if "show" in call and call[:1] == ["git"]]
    assert shown and shown[0][-1] == f"{HEAD}:{MODULE.WEB_WORKFLOW_FILE}"


class LateRunner(FilesRunner):
    """A mirror that learns of the release only when it fetches."""

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        if "fetch" in list(argv):
            self.ancestors.add((OLD, HEAD))
        return super().__call__(argv, **kwargs)


def test_a_release_merged_since_the_mirror_synced_is_fetched_before_answering(
    tmp_path: Path,
) -> None:
    # v1.71 (16 Nov 2026): ac-ship asked before the engine's mirror had the merge.
    runner = LateRunner(["packages/python/ac_platform/x.py"])
    engine = staging(tmp_path, runner)
    assert engine.web_inputs_unchanged(OLD, HEAD)
    assert sum("fetch" in call for call in runner.calls) == 1
    # Already in the mirror: no fetch at all.
    again = FilesRunner(["packages/python/ac_platform/x.py"])
    again.ancestors.add((OLD, HEAD))
    assert staging(tmp_path / "again", again).web_inputs_unchanged(OLD, HEAD)
    assert not any("fetch" in call for call in again.calls)


def test_ac_ship_asks_the_engine_twice_before_waiting_for_a_web_build() -> None:
    """infra/release/web_inputs/ac-ship-retry.patch, for the ac-ship that already carries
    ac-ship.patch: one more answer after a short wait; nothing else in ac-ship changes."""
    patch = (ROOT / "infra/release/web_inputs/ac-ship-retry.patch").read_text(encoding="utf-8")
    removed = [
        line[1:] for line in patch.splitlines() if line.startswith("-") and line[:3] != "---"
    ]
    added = [line[1:] for line in patch.splitlines() if line.startswith("+") and line[:3] != "+++"]
    assert any("for try in 1 2; do" in line for line in added)
    assert any("sleep 30" in line for line in added)
    assert any('ac-release web-unchanged staging "$target"' in line for line in added)
    assert all(
        "deploy" not in line and "fail " not in line and "promote" not in line for line in removed
    )


def test_a_web_change_without_a_web_build_still_stops(tmp_path: Path) -> None:
    runner = FilesRunner(["apps/sales-xray-web/app/page.tsx"])
    runner.ancestors.add((OLD, HEAD))
    engine = staging(tmp_path, runner)
    with pytest.raises(MODULE.ReleaseError, match="no Sales Xray web build"):
        engine.deploy("staging", HEAD, "web", dry_run=False)


def test_ac_ship_asks_the_engine_instead_of_a_copied_list() -> None:
    """infra/release/web_inputs/ac-ship.patch, for the installed ac-ship: its stale recipe pin
    and copied input list go; the engine's web-unchanged answers, for the running source."""
    patch = (ROOT / "infra/release/web_inputs/ac-ship.patch").read_text(encoding="utf-8")
    removed = [
        line[1:] for line in patch.splitlines() if line.startswith("-") and line[:3] != "---"
    ]
    added = [line[1:] for line in patch.splitlines() if line.startswith("+") and line[:3] != "+++"]
    assert any(line.startswith("WEB_RECIPE_BLOB=") for line in removed)
    assert any(line.startswith("WEB_INPUTS=") for line in removed)
    assert not any("WEB_RECIPE_BLOB" in line or "WEB_INPUTS" in line for line in added)
    assert any('ac-release web-unchanged staging "$target"' in line for line in added)
    # Only web_inputs_equal's own lines change; the build wait, the deploys and the gates stay.
    assert all(
        "deploy" not in line and "fail " not in line and "promote" not in line for line in removed
    )


def test_a_running_web_outside_mains_history_is_never_kept(tmp_path: Path) -> None:
    # Not an ancestor (for example a build from before a squash merge): no shortcut.
    engine = staging(tmp_path, FilesRunner(["docs/a.md"]))
    with pytest.raises(MODULE.ReleaseError, match="no Sales Xray web build"):
        engine.deploy("staging", HEAD, "web", dry_run=False)
    assert not engine.web_inputs_unchanged(OLD, HEAD)
