"""Fake GitHub responses prove release pinning and all-or-nothing collection."""

import importlib.util
import io
import json
import shutil
import subprocess
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "collector", ROOT / "scripts/collect_product_notes.py"
)
assert spec is not None and spec.loader is not None
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
SHA = "a" * 40
BODY = "## User-facing note\nTitle: Fictional summary\n- Read a clearer summary.\nFeature: reports"


def fake_git(monkeypatch: pytest.MonkeyPatch, subjects: list[str]) -> None:
    def run(argv, **_kwargs):
        assert argv[1:] == ["log", "--first-parent", "--format=%s", SHA, "--"]
        return subprocess.CompletedProcess(argv, 0, "\n".join(subjects))

    monkeypatch.setattr(collector.subprocess, "run", run)


def test_label_approval_and_invalid_or_none_notes_are_skipped(monkeypatch) -> None:
    fake_git(monkeypatch, ["Newest (#3)", "Skip none (#2)", "Invalid (#1)", "Other #9"])
    requested = []

    def github(request, **_kwargs):
        assert request.full_url.startswith("https://api.github.com/repos/fictional/project/pulls/")
        assert request.headers["Authorization"] == "Bearer fictional-test-token"
        pr = int(request.full_url.rsplit("/", 1)[1])
        requested.append(pr)
        return io.StringIO(
            json.dumps(
                {
                    "body": {
                        3: BODY,
                        2: "## User-facing note\nNONE",
                        1: "## User-facing note\nTitle: Invalid",
                    }[pr],
                    "labels": [{"name": "note-approved"}],
                    "merged_at": "2026-10-01T14:00:00Z",
                }
            )
        )

    monkeypatch.setattr(collector.urllib.request, "urlopen", github)
    result = collector.collect(SHA, "fictional/project", "fictional-test-token")
    assert requested == [3, 2, 1]
    assert result == {
        "version": 1,
        "release_sha": SHA,
        "complete": True,
        "notes": [
            {
                "key": "pr-3",
                "pr": 3,
                "merged_at": "2026-10-01T14:00:00Z",
                "title": "Fictional summary",
                "items": ["Read a clearer summary."],
                "feature_key": "reports",
                "approved": True,
            }
        ],
    }


def test_newest_200_prs_are_collected_and_unlabelled_notes_are_drafts(monkeypatch) -> None:
    fake_git(monkeypatch, [f"Change (#{pr})" for pr in range(201, 0, -1)])
    requested = []

    def github(request, **_kwargs):
        requested.append(int(request.full_url.rsplit("/", 1)[1]))
        return io.StringIO(
            json.dumps({"body": BODY, "labels": [], "merged_at": "2026-10-01T14:00:00Z"})
        )

    monkeypatch.setattr(collector.urllib.request, "urlopen", github)
    result = collector.collect(SHA, "fictional/project", "fictional-test-token")
    assert requested == list(range(201, 1, -1))
    assert len(result["notes"]) == 200 and all(not n["approved"] for n in result["notes"])


@pytest.mark.parametrize("failure", ["http", "invalid-json", "malformed-response"])
def test_error_discards_partial_notes_and_cli_exits_zero(monkeypatch, tmp_path, failure) -> None:
    fake_git(monkeypatch, ["Good (#2)", "Error (#1)"])

    def github(request, **_kwargs):
        if request.full_url.endswith("/2"):
            return io.StringIO(
                json.dumps({"body": BODY, "labels": [], "merged_at": "2026-10-01T14:00:00Z"})
            )
        if failure == "http":
            raise HTTPError(request.full_url, 403, "unavailable", {}, None)
        return io.StringIO("invalid" if failure == "invalid-json" else "null")

    monkeypatch.setattr(collector.urllib.request, "urlopen", github)
    monkeypatch.setenv("GH_TOKEN", "fictional-test-token")
    output = tmp_path / "notes.json"
    assert (
        collector.main(
            ["--output", str(output), "--release-sha", SHA, "--repository", "fictional/project"]
        )
        == 0
    )
    assert json.loads(output.read_text()) == {
        "version": 1,
        "release_sha": SHA,
        "complete": False,
        "notes": [],
    }


def test_packaging_collects_before_build_with_full_history_and_runtime_read_only_copy() -> None:
    workflow = (
        (ROOT / ".github/workflows/application.yml")
        .read_text()
        .split("  package-release-images:")[1]
    )
    assert "pull-requests: read" in workflow and "fetch-depth: 0" in workflow
    assert workflow.index("Collect release-bound product notes") < workflow.index(
        "Build API release image"
    )
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in workflow
    dockerfile = (ROOT / "infra/application/Dockerfile.python").read_text()
    copy = "COPY --chmod=0444 infra/application/product-notes.json /app/product-notes.json"
    assert dockerfile.index("USER root") < dockerfile.index(copy) < dockerfile.index("USER ac")
    assert json.loads((ROOT / "infra/application/product-notes.json").read_text())["notes"] == []


def test_real_first_parent_history_excludes_branch_commits_and_future_changes(
    monkeypatch, tmp_path
):
    git_executable = shutil.which("git")
    assert git_executable is not None

    def git(*args):
        return subprocess.run(  # noqa: S603 - local disposable test repository and fixed argv
            [
                git_executable,
                "-c",
                "user.name=Fictional",
                "-c",
                "user.email=fictional@example.test",
                *args,
            ],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    git("commit", "--allow-empty", "-qm", "Base (#1)")
    git("checkout", "-qb", "feature")
    git("commit", "--allow-empty", "-qm", "Branch subject (#99)")
    git("checkout", "-q", "main")
    git("merge", "--no-ff", "-qm", "Merged feature (#2)", "feature")
    release = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-qm", "Future main (#3)")
    requested = []

    def github(request, **_kwargs):
        requested.append(int(request.full_url.rsplit("/", 1)[1]))
        return io.StringIO(
            json.dumps({"body": BODY, "labels": [], "merged_at": "2026-10-01T14:00:00Z"})
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(collector.urllib.request, "urlopen", github)
    assert collector.collect(release, "fictional/project", "fictional-test-token")["complete"]
    assert requested == [2, 1]


def test_collection_budget_discards_partial_notes(monkeypatch):
    fake_git(monkeypatch, ["Newest (#2)", "Older (#1)"])
    clock = iter([0, 1, 121])
    monkeypatch.setattr(collector.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        collector.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.StringIO(
            json.dumps({"body": BODY, "labels": [], "merged_at": "2026-10-01T14:00:00Z"})
        ),
    )
    result = collector.collect(SHA, "fictional/project", "fictional-test-token")
    assert result["notes"] == [] and result["complete"] is False
