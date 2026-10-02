"""Exact-manifest artifact cleanup (scripts/data-changes/prune-approved-release-artifacts.py).

Every case runs the repository release engine against a fictional application
root under tmp_path: no host paths, Docker, secrets, database or audio.
"""

from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "infra/release/ac_release.py"
SPEC = importlib.util.spec_from_file_location(
    "prune_approved_release_artifacts",
    ROOT / "scripts/data-changes/prune-approved-release-artifacts.py",
)
assert SPEC is not None and SPEC.loader is not None
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)

APPROVED = ["a" * 40, "b" * 40]
UNAPPROVED = "c" * 40
RECENT = [f"{index:040x}" for index in range(1, 11)]
APPROVAL = "AUT-766 comment 0000-fictional approve delete"


def engine_digest() -> str:
    return hashlib.sha256(ENGINE.read_bytes()).hexdigest()


def write_bundle(artifacts: Path, sha: str, age_hours: float) -> None:
    bundle = artifacts / sha
    bundle.mkdir()
    for name, size in (
        ("SHA256SUMS", 120),
        ("application-images.tar.gz", 4000),
        ("release-images.env", 300),
    ):
        (bundle / name).write_bytes(b"x" * size)
    stamp = time.time() - age_hours * 3600
    os.utime(bundle, (stamp, stamp))


def tree_bytes(path: Path) -> int:
    return sum(child.lstat().st_size for child in path.iterdir())


class Fixture:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.application = tmp_path / "application"
        self.artifacts = self.application / "artifacts"
        self.artifacts.mkdir(parents=True)
        for index, sha in enumerate(RECENT):
            write_bundle(self.artifacts, sha, age_hours=index + 1)
        for index, sha in enumerate([*APPROVED, UNAPPROVED]):
            write_bundle(self.artifacts, sha, age_hours=100 + index)
        self.manifest = self.write_manifest(self.manifest_data())
        self.engines: list[Any] = []

    def manifest_data(self) -> dict[str, Any]:
        entries = []
        for sha in APPROVED:
            size = tree_bytes(self.artifacts / sha)
            entries.append(
                {
                    "sha": sha,
                    "path": f"{TOOL.ARTIFACTS_ROOT}/{sha}",
                    "bytes": size,
                    "allocated_regular_bytes": size + 96,
                    "conservative_reclaimable_file_bytes": size + 96,
                    "hardlinked_allocated_regular_bytes": 0,
                    "keep": [],
                }
            )
        return {
            "schema_version": 1,
            "artifacts_root": TOOL.ARTIFACTS_ROOT,
            "keep_recent": 10,
            "artifact_count": len(entries),
            "artifacts": entries,
            "images": [],
            "leftovers": [],
            "status": "proposal_only_not_approved_deletion",
        }

    def write_manifest(self, data: dict[str, Any]) -> Path:
        path = self.tmp / "manifest.json"
        path.write_text(json.dumps(data, indent=2, sort_keys=True))
        return path

    def make_engine(self, module: Any) -> Any:
        paths = module.Paths(
            state=self.tmp / "state",
            logs=self.tmp / "logs",
            store=self.tmp / "store",
            config=self.tmp / "config",
            application=self.application,
            stage_root=self.tmp,
            lock=self.tmp / "ac-release.lock",
            foundation=self.tmp / "foundation",
            sales_xray=self.tmp / "sales-xray",
            engine=self.tmp / "engine",
        )
        engine = module.Engine(paths=paths)
        self.engines.append(engine)
        return engine

    def argv(self, *extra: str, manifest_sha: str | None = None) -> list[str]:
        digest = manifest_sha or hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        return [
            "--manifest",
            str(self.manifest),
            "--manifest-sha256",
            digest,
            "--engine-sha256",
            engine_digest(),
            *extra,
        ]

    def run(
        self,
        capsys: pytest.CaptureFixture[str],
        *extra: str,
        manifest_sha: str | None = None,
        engine_sha: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        argv = self.argv(*extra, manifest_sha=manifest_sha)
        if engine_sha:
            argv[argv.index("--engine-sha256") + 1] = engine_sha
        code = TOOL.main(argv, engine_path=ENGINE, make_engine=self.make_engine)
        return code, json.loads(capsys.readouterr().out)

    def history(self) -> list[dict[str, Any]]:
        path = self.tmp / "state" / "history.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def present(self) -> set[str]:
        return {path.name for path in self.artifacts.iterdir()}


@pytest.fixture
def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fixture:
    monkeypatch.setattr(TOOL.os, "geteuid", lambda: 0, raising=False)
    yield Fixture(tmp_path)
    sys.modules.pop("ac_release", None)


APPLY = ("--apply", "--approval-ref", APPROVAL)


def test_dry_run_reports_and_removes_nothing(fixture: Fixture, capsys) -> None:
    before = fixture.present()
    code, outcome = fixture.run(capsys)
    assert code == 0
    assert outcome["result"] == "dry-run"
    assert sorted(outcome["would_remove"]) == APPROVED
    assert outcome["would_free_bytes"] == sum(tree_bytes(fixture.artifacts / s) for s in APPROVED)
    assert outcome["unapproved_eligible_untouched"] == 1
    assert fixture.present() == before
    assert fixture.history() == []


def test_apply_removes_only_approved_and_keeps_new_eligible_artifact(
    fixture: Fixture, capsys
) -> None:
    freed = sum(tree_bytes(fixture.artifacts / sha) for sha in APPROVED)
    code, outcome = fixture.run(capsys, *APPLY)
    assert code == 0, outcome
    assert fixture.present() == {*RECENT, UNAPPROVED}
    assert sorted(outcome["removed"]) == APPROVED
    entry = fixture.history()[-1]
    assert entry["action"] == "prune-approved-artifacts"
    assert entry["result"] == "applied"
    assert entry["issue"] == "AUT-766"
    assert entry["approval_ref"] == APPROVAL
    assert entry["manifest_sha256"] == hashlib.sha256(fixture.manifest.read_bytes()).hexdigest()
    assert entry["engine_sha256"] == engine_digest()
    assert sorted(entry["removed"]) == APPROVED
    assert entry["removed_count"] == 2
    assert entry["freed_bytes"] == freed
    assert entry["errors"] == []
    assert entry["unapproved_eligible_untouched"] == 1


def test_repeat_after_approved_artifacts_are_absent_is_safe(fixture: Fixture, capsys) -> None:
    assert fixture.run(capsys, *APPLY)[0] == 0
    code, outcome = fixture.run(capsys, *APPLY)
    assert code == 0
    assert outcome["removed"] == []
    assert sorted(outcome["absent"]) == APPROVED
    assert fixture.present() == {*RECENT, UNAPPROVED}
    assert [entry["result"] for entry in fixture.history()] == ["applied", "applied"]


def test_approved_artifact_that_became_retained_stops_every_removal(
    fixture: Fixture, capsys
) -> None:
    intent = fixture.application / "operator-inputs" / "staging" / "install.intent.json"
    intent.parent.mkdir(parents=True)
    intent.write_text(json.dumps({"bundle": f"{TOOL.ARTIFACTS_ROOT}/{APPROVED[1]}"}))
    code, outcome = fixture.run(capsys, *APPLY)
    assert code == 1
    assert {*APPROVED, UNAPPROVED} <= fixture.present()
    entry = fixture.history()[-1]
    assert entry["result"] == "refused"
    assert entry["removed"] == []
    assert entry["refused"] == [
        f"artifacts/{APPROVED[1]} is now retained: named in "
        "operator-inputs/staging/install.intent.json"
    ]


def _edit_manifest(change: Callable[[dict[str, Any]], None]) -> Callable[[Fixture], dict]:
    def apply_change(fixture: Fixture) -> dict:
        data = fixture.manifest_data()
        change(data)
        fixture.manifest = fixture.write_manifest(data)
        return {}

    return apply_change


def _entry(index: int, **values: Any) -> Callable[[dict[str, Any]], None]:
    return lambda data: data["artifacts"][index].update(values)


def _symlink_bundle(fixture: Fixture) -> dict:
    target = fixture.tmp / "elsewhere"
    (fixture.artifacts / APPROVED[0]).rename(target)
    (fixture.artifacts / APPROVED[0]).symlink_to(target, target_is_directory=True)
    return {}


def _keep_age(bundle: Path) -> None:
    # A changed entry list moves the directory mtime; keep it old so the
    # bundle check, not "one of the 10 newest", is what refuses the run.
    stamp = time.time() - 100 * 3600
    os.utime(bundle, (stamp, stamp))


def _symlink_inside(fixture: Fixture) -> dict:
    bundle = fixture.artifacts / APPROVED[0]
    (bundle / "release-images.env").rename(fixture.tmp / "release-images.env")
    (bundle / "release-images.env").symlink_to(fixture.tmp / "release-images.env")
    _keep_age(bundle)
    return {}


def _grow(fixture: Fixture) -> dict:
    with (fixture.artifacts / APPROVED[0] / "SHA256SUMS").open("ab") as handle:
        handle.write(b"y")
    return {}


def _extra_file(fixture: Fixture) -> dict:
    (fixture.artifacts / APPROVED[0] / "notes.txt").write_bytes(b"")
    _keep_age(fixture.artifacts / APPROVED[0])
    return {}


def _duplicate(data: dict[str, Any]) -> None:
    data["artifacts"].append(dict(data["artifacts"][0]))
    data["artifact_count"] = len(data["artifacts"])


TAMPERING: dict[str, Callable[[Fixture], dict]] = {
    "manifest digest": lambda fixture: {"manifest_sha": "0" * 64},
    "engine digest": lambda fixture: {"engine_sha": "0" * 64},
    "path outside root": _edit_manifest(_entry(0, path=f"/srv/other/{APPROVED[0]}")),
    "path of another id": _edit_manifest(_entry(0, path=f"{TOOL.ARTIFACTS_ROOT}/{APPROVED[1]}")),
    "uppercase id": _edit_manifest(
        _entry(0, sha="A" * 40, path=f"{TOOL.ARTIFACTS_ROOT}/{'A' * 40}")
    ),
    "short id": _edit_manifest(_entry(0, sha="a" * 12, path=f"{TOOL.ARTIFACTS_ROOT}/{'a' * 12}")),
    "duplicate id": _edit_manifest(_duplicate),
    "retained entry": _edit_manifest(_entry(0, keep=["one of the 10 newest"])),
    "negative size": _edit_manifest(_entry(0, bytes=-1)),
    "extra entry field": _edit_manifest(_entry(0, mode="force")),
    "images listed": _edit_manifest(lambda data: data.update(images=[{"id": "x"}])),
    "leftovers listed": _edit_manifest(lambda data: data.update(leftovers=[".prune-x"])),
    "other root": _edit_manifest(lambda data: data.update(artifacts_root="/srv")),
    "smaller keep": _edit_manifest(lambda data: data.update(keep_recent=1)),
    "wrong count": _edit_manifest(lambda data: data.update(artifact_count=1)),
    "unknown field": _edit_manifest(lambda data: data.update(root_override="/")),
    "manifest size": _edit_manifest(_entry(0, bytes=1)),
    "bundle grew": _grow,
    "bundle is a symlink": _symlink_bundle,
    "symlink inside bundle": _symlink_inside,
    "unexpected bundle file": _extra_file,
}


@pytest.mark.parametrize("case", sorted(TAMPERING))
def test_tampering_fails_before_any_removal(fixture: Fixture, capsys, case: str) -> None:
    overrides = TAMPERING[case](fixture)
    code, outcome = fixture.run(capsys, *APPLY, **overrides)
    assert code == 1
    assert outcome["result"] in {"refused"}
    assert {*APPROVED, UNAPPROVED, *RECENT} <= fixture.present()
    assert not any(name.startswith(".prune-") for name in fixture.present())
    assert all(entry["removed"] == [] for entry in fixture.history())


def test_apply_needs_root_and_an_approval_reference(
    fixture: Fixture, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SystemExit) as stopped:
        TOOL.main(fixture.argv("--apply"), engine_path=ENGINE, make_engine=fixture.make_engine)
    assert stopped.value.code == 2
    capsys.readouterr()
    monkeypatch.setattr(TOOL.os, "geteuid", lambda: 1000, raising=False)
    code, outcome = fixture.run(capsys, *APPLY)
    assert code == 1
    assert outcome["error"] == "--apply must run as root"
    assert {*APPROVED} <= fixture.present()
    assert fixture.history() == []


def _held(path: Path) -> bool:
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False


def test_removal_and_history_happen_under_both_locks(fixture: Fixture, capsys) -> None:
    seen: list[tuple[str, bool, bool]] = []
    locks = (fixture.tmp / "ac-release.lock", fixture.application / ".deployment.lock")

    def make_engine(module: Any) -> Any:
        engine = fixture.make_engine(module)
        remove, record = engine._remove_unretained, engine.record

        def spy_remove(report: Any) -> Any:
            assert report["images"] == [] and report["leftovers"] == []
            assert sorted(item["sha"] for item in report["artifacts"]) == APPROVED
            seen.append(("remove", *map(_held, locks)))
            return remove(report)

        def spy_record(entry: Any) -> None:
            seen.append(("record", *map(_held, locks)))
            record(entry)

        engine._remove_unretained, engine.record = spy_remove, spy_record
        return engine

    code = TOOL.main(fixture.argv(*APPLY), engine_path=ENGINE, make_engine=make_engine)
    capsys.readouterr()
    assert code == 0
    assert seen == [("remove", True, True), ("record", True, True)]
    assert not any(map(_held, locks))


def test_running_install_refuses_apply(fixture: Fixture, capsys) -> None:
    with (fixture.application / ".deployment.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        code, outcome = fixture.run(capsys, *APPLY)
    assert code == 1
    assert "deployment is running" in outcome["error"]
    assert {*APPROVED} <= fixture.present()


def test_history_write_failure_after_removal_is_reported_as_failed(
    fixture: Fixture, capsys
) -> None:
    def make_engine(module: Any) -> Any:
        engine = fixture.make_engine(module)

        def broken_record(entry: Any) -> None:
            raise OSError(28, "No space left on device")

        engine.record = broken_record
        return engine

    code = TOOL.main(fixture.argv(*APPLY), engine_path=ENGINE, make_engine=make_engine)
    outcome = json.loads(capsys.readouterr().out)
    assert code == 1
    assert outcome["result"] == "failed"
    assert sorted(outcome["removed"]) == APPROVED
    assert "No space left" in outcome["history_error"]
