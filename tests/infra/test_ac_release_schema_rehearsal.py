"""Real fictional Git + authenticated test receipts; no root/Docker/live access."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.infra.test_ac_release import DIGEST, MODULE, make_engine
from tests.infra.test_trusted_rehearsal import CONFIG, KEY, NOW, h, record


@pytest.fixture
def release(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    mirror = engine.paths.mirror
    (mirror / "HEAD").unlink()
    subprocess.run(  # noqa: S603 - fictional temporary repository, fixed executable
        ["/usr/bin/git", "init", "--bare", "--quiet", str(mirror)], check=True
    )

    def git(*args, data=None):
        return subprocess.run(  # noqa: S603 - fictional object construction, no candidate code
            ["/usr/bin/git", "--no-replace-objects", f"--git-dir={mirror}", *args],
            input=data,
            capture_output=True,
            text=True,
            check=True,
            env={
                "PATH": os.environ["PATH"],
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_AUTHOR_NAME": "Fictional",
                "GIT_AUTHOR_EMAIL": "fictional@example.invalid",
                "GIT_COMMITTER_NAME": "Fictional",
                "GIT_COMMITTER_EMAIL": "fictional@example.invalid",
            },
        ).stdout.strip()

    def commit(files, parent=None):
        def tree(entries):
            rows, directories = [], {}
            for name, contents in entries.items():
                prefix, sep, rest = name.partition("/")
                if sep:
                    directories.setdefault(prefix, {})[rest] = contents
                else:
                    blob = git("hash-object", "-w", "--stdin", data=contents)
                    rows.append(f"100644 blob {blob}\t{name}\n")
            for name, contents in directories.items():
                rows.append(f"040000 tree {tree(contents)}\t{name}\n")
            return git("mktree", data="".join(sorted(rows)))

        return git("commit-tree", tree(files), *(["-p", parent] if parent else []), data="fixture")

    old = {"db/migrations/versions/old.py": "old revision", "README.md": "old"}
    base = commit(old)
    current = [base]
    engine.current_core = lambda _environment: current[0]
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    calls = []

    def receipt(candidate, **changes):
        path = receipts / f"{candidate}-{base}.json"
        value = record(candidate=candidate, base=base, release_id=base, **changes)
        path.write_text(json.dumps(h.seal(value, KEY)))
        return path

    def run(argv, **kwargs):
        calls.append(list(argv))
        if argv[0] == MODULE.SCHEMA_REHEARSAL:
            assert list(argv[1:]) == ["verify", "--candidate", argv[3], "--base", current[0]]
            assert kwargs == {"check": False, "timeout": 30}
            try:
                envelope = json.loads((receipts / f"{argv[3]}-{argv[5]}.json").read_bytes())
                h.validate_receipt(envelope, KEY, CONFIG, argv[3], argv[5], NOW)
            except (OSError, ValueError, TypeError, KeyError, h.Refusal):
                return subprocess.CompletedProcess(argv, 1, "schema-rehearsal: FAIL", "")
            return subprocess.CompletedProcess(argv, 0, MODULE.SCHEMA_REHEARSAL_SUCCESS + "\n", "")
        assert argv[0] == "git"
        return MODULE.run_command(argv, **kwargs)

    engine.run = run
    engine.main_head = lambda: current[0]
    engine.is_ancestor = lambda *_: True
    engine.prune_store = lambda: []
    monkeypatch.setenv("AC_SCHEMA_REHEARSAL", str(tmp_path / "candidate-validator"))
    return engine, base, old, commit, receipt, calls, current


@pytest.mark.parametrize("change", ["add", "edit", "delete", "rename", "environment"])
def test_real_migration_tree_changes_require_exact_passing_receipt(release, change):
    engine, base, old, commit, receipt, calls, _ = release
    files = dict(old)
    if change == "add":
        files["db/migrations/versions/new.py"] = "new revision"
    elif change == "edit":
        files["db/migrations/versions/old.py"] = "edited revision"
    elif change == "delete":
        del files["db/migrations/versions/old.py"]
    elif change == "rename":
        files["db/migrations/versions/renamed.py"] = files.pop("db/migrations/versions/old.py")
    else:
        files["db/migrations/env.py"] = "changed environment"
    candidate = commit(files, base)
    with pytest.raises(MODULE.ReleaseError, match="receipt rejected"):
        engine.require_schema_rehearsal(candidate)
    receipt(candidate)
    engine.require_schema_rehearsal(candidate)
    assert calls[-1] == [
        MODULE.SCHEMA_REHEARSAL,
        "verify",
        "--candidate",
        candidate,
        "--base",
        base,
    ]


def test_unchanged_migrations_need_no_validator_and_git_helpers_do_not_execute(release, tmp_path):
    engine, base, old, commit, _, calls, _ = release
    sentinel = tmp_path / "external-helper-ran"
    helper = tmp_path / "helper"
    helper.write_text(f"#!/bin/sh\ntouch '{sentinel}'\nexit 0\n")
    helper.chmod(0o755)
    MODULE.run_command(
        ["git", f"--git-dir={engine.paths.mirror}", "config", "diff.external", str(helper)]
    )
    files = {**old, "README.md": "changed"}
    candidate = commit(files, base)
    engine.require_schema_rehearsal(candidate)
    assert len(calls) == 1 and calls[0][0] == "git"
    candidate = commit({**files, "db/migrations/versions/new.py": "revision"}, candidate)
    with pytest.raises(MODULE.ReleaseError, match="receipt rejected"):
        engine.require_schema_rehearsal(candidate)
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "defect", ["missing", "failed", "candidate", "base", "stale", "forged", "pin", "legacy"]
)
def test_invalid_receipts_cannot_reach_an_installer(release, defect):
    engine, base, old, commit, receipt, _, _ = release
    candidate = commit({**old, "db/migrations/versions/new.py": "new"}, base)
    path = receipt(candidate)
    envelope = json.loads(path.read_text())
    if defect == "missing":
        path.unlink()
    elif defect == "legacy":
        path.write_text(json.dumps({"candidate": candidate, "base": base, "result": "PASS"}))
    else:
        changes = {
            "failed": {"result": "FAIL"},
            "candidate": {"candidate": base},
            "base": {"base": candidate},
            "stale": {"finished_at": "2026-10-24T09:00:00+00:00"},
            "pin": {"bundle_sha256": "0" * 64},
        }
        if defect == "forged":
            envelope = h.seal(envelope["record"], b"fictional-attacker-key")
        else:
            envelope = h.seal(envelope["record"] | changes[defect], KEY)
        path.write_text(json.dumps(envelope))
    engine.store_bundle = lambda *_: pytest.fail("must refuse before storing/running candidate")
    build = MODULE.Build(candidate, 1, 1, "fictional", DIGEST)
    with pytest.raises(MODULE.ReleaseError, match="receipt rejected"):
        engine.deploy_core("staging", build)


@pytest.mark.parametrize("route", ["manual", "auto", "direct", "dry-run"])
def test_all_staging_core_routes_refuse_before_candidate_side_effects(release, monkeypatch, route):
    engine, base, old, commit, _, _, _ = release
    candidate = commit({**old, "db/migrations/versions/new.py": "new"}, base)
    build = MODULE.Build(candidate, 1, 1, "fictional", DIGEST)
    engine.store_bundle = lambda *_: pytest.fail("candidate side effect before receipt")
    engine.new_log = lambda *_: pytest.fail("candidate log created before receipt")
    monkeypatch.setattr(MODULE, "core_candidate", lambda *_: MODULE.Candidate("ready", build=build))
    if route == "direct":
        with pytest.raises(MODULE.ReleaseError, match="receipt rejected"):
            engine.deploy_core("staging", build)
        return
    if route == "auto":
        results = engine.advance("staging", candidate)
    else:
        results = engine.deploy("staging", candidate, "core", dry_run=route == "dry-run")
    assert len(results) == 1 and results[0]["result"] == "failed"
    assert "receipt rejected" in results[0]["error"]
    assert engine.current_core("staging") == base


def test_exact_pass_reaches_core_work_but_never_reuses_receipt_for_new_base(release):
    engine, base, old, commit, receipt, _, current = release
    candidate = commit({**old, "db/migrations/versions/new.py": "new"}, base)
    receipt(candidate)
    engine.new_log = lambda *_: pytest.fail("receipt passed and core work reached")
    build = MODULE.Build(candidate, 1, 1, "fictional", DIGEST)
    with pytest.raises(pytest.fail.Exception, match="core work reached"):
        engine.deploy_core("staging", build)
    current[0] = commit({**old, "README.md": "new staging base"}, base)
    with pytest.raises(MODULE.ReleaseError, match="receipt rejected"):
        engine.deploy_core("staging", build)


@pytest.mark.parametrize(
    "defect",
    [
        "unknown-base",
        "missing-object",
        "missing-verifier",
        "timeout",
        "legacy-verifier",
        "base-moved",
    ],
)
def test_unavailable_or_racing_admission_fails_closed(release, defect):
    engine, base, old, commit, receipt, _, current = release
    candidate = commit({**old, "db/migrations/versions/new.py": "new"}, base)
    receipt(candidate)
    run = engine.run

    def interrupted(argv, **kwargs):
        if argv[0] != MODULE.SCHEMA_REHEARSAL:
            return run(argv, **kwargs)
        if defect == "missing-verifier":
            raise FileNotFoundError
        if defect == "timeout":
            raise subprocess.TimeoutExpired(argv, 30)
        result = run(argv, **kwargs)
        if defect == "legacy-verifier":
            return subprocess.CompletedProcess(argv, 0, "PASS", "")
        if defect == "base-moved":
            current[0] = candidate
        return result

    engine.run = interrupted
    if defect == "unknown-base":
        current[0] = None
    elif defect == "missing-object":
        candidate = "0" * 40
    with pytest.raises(MODULE.ReleaseError):
        engine.require_schema_rehearsal(candidate)


def test_validator_uses_the_owner_required_receipt_store():
    assert Path("/var/lib/ac-release/schema-rehearsal") == h.RECEIPTS


@pytest.mark.parametrize("environment,rollback", [("production", False), ("staging", True)])
def test_application_only_rollback_and_production_keep_existing_admission(
    release, environment, rollback
):
    engine, base, old, commit, _, _, _ = release
    candidate = commit({**old, "db/migrations/versions/new.py": "new"}, base)
    engine.require_schema_rehearsal = lambda *_: pytest.fail("unexpected staging admission")
    engine.new_log = lambda *_: pytest.fail("existing core path reached")
    build = MODULE.Build(candidate, 1, 1, "fictional", DIGEST)
    with pytest.raises(pytest.fail.Exception, match="existing core path reached"):
        engine.deploy_core(environment, build, rollback_only=rollback)
