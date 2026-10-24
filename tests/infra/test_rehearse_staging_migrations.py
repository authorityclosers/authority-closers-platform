"""The on-server migration rehearsal (AUT-2215): the gate's contract, no GitHub artifact."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "rehearse_staging_migrations", ROOT / "infra/release/rehearse-staging-migrations.py"
)
assert SPEC and SPEC.loader
rehearsal = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rehearsal
SPEC.loader.exec_module(rehearsal)

REAL_RUN = rehearsal.run
MANIFEST = {
    "alembic_revision": "20261023_0127",
    "dump_sha256": "a" * 64,
    "environment": "staging",
    "exported_at": "2026-10-24T08:00:00+00:00",
    "postgres_version_num": 180006,
    "release_id": "b" * 40,
    "schema": "ac.migration_schema/1",
    "schema_only": True,
}


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed git argv in a fixture repository
        ["git", "-C", str(repo), *arguments],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def workbench(tmp_path: Path, *, migration: bool) -> tuple[Path, str, str]:
    repo = tmp_path / "workbench"
    (repo / "db/migrations/versions").mkdir(parents=True)
    git(repo.parent, "init", "--quiet", str(repo))
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    (repo / "db/migrations/versions/0127.py").write_text("revision = '0127'\n")
    (repo / "README.md").write_text("base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    if migration:
        (repo / "db/migrations/versions/0128.py").write_text("revision = '0128'\n")
    (repo / "README.md").write_text("candidate\n")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "candidate")
    return repo, base, git(repo, "rev-parse", "HEAD")


class FakeTools:
    """Real git; the uv sync, the staging exporter and the gate are recorded fakes."""

    def __init__(
        self, *, export_ok: bool = True, gate: tuple[int, str] = (0, "PASS (1 revisions)")
    ):
        self.export_ok, self.gate = export_ok, gate
        self.calls: list[tuple[list[str], dict[str, str] | None]] = []
        self.trusted: list[str] = []

    def __call__(self, command, *, cwd=None, env=None, timeout):
        if command[0] == "git":
            if "clone" in command:
                # Root clones acdev's workbench: git drops -c config for the local clone's
                # upload-pack, so the run's private global config must trust both paths.
                assert "-c" not in command
                self.trusted = Path(env["GIT_CONFIG_GLOBAL"]).read_text().splitlines()
            return REAL_RUN(command, cwd=cwd, env=env, timeout=timeout)
        self.calls.append((list(command), env))
        if "sync" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        if "scripts/ops/export_migration_schema.py" in command:
            if not self.export_ok:
                return subprocess.CompletedProcess(
                    command,
                    1,
                    "",
                    "schema-export: FAIL (The exact staging release is unavailable.)\n",
                )
            pair = Path(command[command.index("--output") + 1])
            pair.mkdir(mode=0o700)
            (pair / "schema.dump").write_bytes(b"PGDMP fictional")
            (pair / "manifest.json").write_text(json.dumps(MANIFEST, sort_keys=True))
            return subprocess.CompletedProcess(
                command, 0, "schema-export: PASS (schema-only export)\n", ""
            )
        if "scripts/ci/migration_schema_gate.py" in command:
            code, line = self.gate
            return subprocess.CompletedProcess(command, code, f"migration-safety: {line}\n", "")
        raise AssertionError(f"unexpected command {command}")

    def named(self, script: str) -> list[tuple[list[str], dict[str, str] | None]]:
        return [call for call in self.calls if script in call[0]]


@pytest.fixture
def as_root(monkeypatch):
    monkeypatch.setattr(rehearsal.os, "geteuid", lambda: 0, raising=False)


def invoke(tmp_path: Path, repo: Path, base: str, candidate: str) -> int:
    (tmp_path / "scratch").mkdir(exist_ok=True)
    return rehearsal.main(
        [
            "--workbench",
            str(repo),
            "--candidate",
            candidate,
            "--base",
            base,
            "--receipts",
            str(tmp_path / "receipts"),
            "--scratch",
            str(tmp_path / "scratch"),
        ]
    )


def receipt(tmp_path: Path) -> dict:
    (path,) = (tmp_path / "receipts").glob("*.json")
    assert path.stat().st_mode & 0o777 == 0o640
    return json.loads(path.read_text())


def test_unchanged_migrations_pass_without_touching_staging(tmp_path, monkeypatch, capsys, as_root):
    repo, base, candidate = workbench(tmp_path, migration=False)
    tools = FakeTools()
    monkeypatch.setattr(rehearsal, "run", tools)
    assert invoke(tmp_path, repo, base, candidate) == 0
    assert capsys.readouterr().out == "schema-rehearsal: PASS (no migration changes)\n"
    assert tools.calls == []
    assert receipt(tmp_path)["result"] == "PASS"


def test_new_migration_rehearses_the_live_staging_export_with_its_manifest_hash(
    tmp_path, monkeypatch, capsys, as_root
):
    repo, base, candidate = workbench(tmp_path, migration=True)
    monkeypatch.setenv("AC_DATABASE_URL", "postgresql://not-for-the-gate")
    monkeypatch.setenv("PGPASSWORD", "not-for-the-gate")
    monkeypatch.setenv("GH_TOKEN", "not-for-the-gate")
    tools = FakeTools()
    monkeypatch.setattr(rehearsal, "run", tools)
    assert invoke(tmp_path, repo, base, candidate) == 0
    assert capsys.readouterr().out == "schema-rehearsal: PASS (1 revisions)\n"
    ((gate, environment),) = tools.named("scripts/ci/migration_schema_gate.py")
    assert gate[gate.index("--base-ref") + 1] == base
    manifest_bytes = json.dumps(MANIFEST, sort_keys=True).encode()
    assert gate[gate.index("--manifest-sha256") + 1] == hashlib.sha256(manifest_bytes).hexdigest()
    assert gate[:4] == ["nice", "-n", "10", "ionice"]
    assert environment is not None
    assert not {"AC_DATABASE_URL", "PGPASSWORD", "GH_TOKEN"} & set(environment)
    record = receipt(tmp_path)
    assert (
        record["result"] == "PASS" and record["candidate"] == candidate and record["base"] == base
    )
    assert record["alembic_revision"] == "20261023_0127"
    assert record["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    # Identities and hashes only: no schema contents.
    assert set(record) == {
        "schema",
        "candidate",
        "base",
        "started_at",
        "finished_at",
        "seconds",
        "result",
        "reason",
        "alembic_revision",
        "dump_sha256",
        "exported_at",
        "postgres_version_num",
        "release_id",
        "manifest_sha256",
    }
    workbench_path = repo.resolve()
    assert tools.trusted == [
        "[safe]",
        f"\tdirectory = {workbench_path}",
        f"\tdirectory = {workbench_path}/.git",
    ]
    assert "GIT_CONFIG_GLOBAL" not in environment
    # The clone, the export and the run's trust file are all gone.
    assert list((tmp_path / "scratch").iterdir()) == []


def test_gate_refusal_stops_the_release_with_its_reason(tmp_path, monkeypatch, capsys, as_root):
    repo, base, candidate = workbench(tmp_path, migration=True)
    tools = FakeTools(gate=(1, "FAIL (downgrade did not restore the baseline schema)"))
    monkeypatch.setattr(rehearsal, "run", tools)
    assert invoke(tmp_path, repo, base, candidate) == 1
    assert capsys.readouterr().out == (
        "schema-rehearsal: FAIL (downgrade did not restore the baseline schema)\n"
    )
    assert receipt(tmp_path)["result"] == "FAIL"
    assert list((tmp_path / "scratch").iterdir()) == []


def test_export_failure_fails_closed_before_the_gate(tmp_path, monkeypatch, capsys, as_root):
    repo, base, candidate = workbench(tmp_path, migration=True)
    tools = FakeTools(export_ok=False)
    monkeypatch.setattr(rehearsal, "run", tools)
    assert invoke(tmp_path, repo, base, candidate) == 1
    assert capsys.readouterr().out == (
        "schema-rehearsal: FAIL (staging export failed: "
        "The exact staging release is unavailable.)\n"
    )
    assert tools.named("scripts/ci/migration_schema_gate.py") == []
    assert list((tmp_path / "scratch").iterdir()) == []


def test_gate_exit_status_must_match_its_result_line(tmp_path, monkeypatch, capsys, as_root):
    repo, base, candidate = workbench(tmp_path, migration=True)
    monkeypatch.setattr(rehearsal, "run", FakeTools(gate=(1, "PASS (1 revisions)")))
    assert invoke(tmp_path, repo, base, candidate) == 1
    assert "result and exit status disagree" in capsys.readouterr().out


def test_release_commit_must_contain_its_base(tmp_path, monkeypatch, capsys, as_root):
    repo, base, candidate = workbench(tmp_path, migration=True)
    tools = FakeTools()
    monkeypatch.setattr(rehearsal, "run", tools)
    assert invoke(tmp_path, repo, candidate, base) == 1
    assert "does not contain its base" in capsys.readouterr().out
    assert tools.calls == []


def test_unknown_or_short_commits_are_refused(tmp_path, monkeypatch, capsys, as_root):
    repo, base, candidate = workbench(tmp_path, migration=True)
    monkeypatch.setattr(rehearsal, "run", FakeTools())
    assert invoke(tmp_path, repo, base, "c" * 40) == 1
    assert "is not in the workbench" in capsys.readouterr().out
    assert invoke(tmp_path, repo, base[:12], candidate) == 1
    assert "full 40-character SHAs" in capsys.readouterr().out


def test_refuses_without_root(tmp_path, monkeypatch, capsys):
    repo, base, candidate = workbench(tmp_path, migration=True)
    monkeypatch.setattr(rehearsal.os, "geteuid", lambda: 1000, raising=False)
    tools = FakeTools()
    monkeypatch.setattr(rehearsal, "run", tools)
    assert invoke(tmp_path, repo, base, candidate) == 1
    assert "run as root" in capsys.readouterr().out
    assert tools.calls == []
