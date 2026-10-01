"""Same-build backup installation, without host services or database changes."""

from __future__ import annotations

import hashlib
import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from tests.infra.test_ac_release import (
    DIGEST,
    HEAD,
    MODULE,
    OLD,
    OUTSIDE,
    FakeRunner,
    bundle_with_head,
    foundation_backup_tool,
    make_engine,
)

MIGRATION = "20260930_0061"
PREVIOUS_MIGRATION = "20260930_0060"


class FoundationRunner(FakeRunner):
    def __init__(self, heads, *, exit_code=0, updates_tool=True, raises=None):
        super().__init__()
        self.heads = heads
        self.exit_code = exit_code
        self.updates_tool = updates_tool
        self.raises = raises
        self.engine = None
        self.operations = []
        self.archives = {}
        self.history_at_core = []

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.operations.append((argv, kwargs))
        if argv[0] == "git" and "archive" in argv:
            archive = Path(
                next(arg.removeprefix("--output=") for arg in argv if arg.startswith("--output="))
            )
            prefix = argv[-1]
            files = (
                {
                    "scripts/ac-postgres-backup.py": "\n".join(
                        f'HEAD_{i} = "{head}"' for i, head in enumerate(self.heads)
                    ),
                    "scripts/install-foundation-release.sh": "# foundation fixture\n",
                }
                if prefix == "infra/vps-foundation"
                else {
                    "scripts/verify-release-archive.py": "# verifier fixture\n",
                    "scripts/install-application-release.sh": "# AC_CORE_ROLLBACK_ONLY\n",
                }
            )
            with tarfile.open(archive, "w") as handle:
                for name, content in files.items():
                    data = content.encode()
                    member = tarfile.TarInfo(f"{prefix}/{name}")
                    member.size = len(data)
                    handle.addfile(member, io.BytesIO(data))
            self.archives[str(archive)] = hashlib.sha256(archive.read_bytes()).hexdigest()
        elif argv[0] == "python3":
            pass
        elif argv[0] == "bash":
            assert self.engine is not None
            if argv[1].endswith("install-foundation-release.sh"):
                if self.raises is not None:
                    raise self.raises
                if self.exit_code == 0 and self.updates_tool:
                    self.engine.paths.backup_tool.parent.mkdir(parents=True, exist_ok=True)
                    self.engine.paths.backup_tool.write_text(
                        Path(argv[1]).with_name("ac-postgres-backup.py").read_text()
                    )
                return subprocess.CompletedProcess(argv, self.exit_code, "", "")
            self.history_at_core = self.engine.history()
        else:
            return super().__call__(argv, **kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def installers(self):
        return [(argv, kwargs) for argv, kwargs in self.operations if argv[0] == "bash"]


def setup(tmp_path, *, candidate_heads=(MIGRATION, PREVIOUS_MIGRATION), **kwargs):
    runner = FoundationRunner(candidate_heads, **kwargs)
    engine = make_engine(tmp_path, runner=runner)
    runner.engine = engine
    bundle = bundle_with_head(tmp_path, MIGRATION)
    for name in MODULE.CORE_FILES - {"release-images.env"}:
        (bundle / name).write_text("fixture\n")
    engine.store_bundle = lambda *args: bundle
    engine.keep_native_build = lambda *args: None
    engine.prepare_activation = lambda *args, **kwargs: {}
    engine.check_core = lambda *args: None
    engine.prune_store = lambda: []
    build = MODULE.Build(HEAD, 100, 7, "ac-application-" + HEAD, DIGEST)
    return engine, runner, build


def running_core(engine, environment, sha, migration):
    release = engine.paths.application / "releases" / sha
    release.mkdir(parents=True)
    (release / "release-images.env").write_text(f"AC_MIGRATION_HEAD={migration}\n")
    (engine.paths.application / f"current-{environment}").symlink_to(release)


def test_unknown_head_installs_exact_build_once_before_core(tmp_path):
    engine, runner, build = setup(tmp_path)
    running_core(engine, "staging", OLD, PREVIOUS_MIGRATION)
    foundation_backup_tool(engine, PREVIOUS_MIGRATION)
    result = engine.attempt("staging", "core", build, dry_run=False, trigger="auto")
    assert result["result"] == "success"
    (foundation, options), (core, _) = runner.installers()
    assert foundation[1].endswith(
        "foundation-source/infra/vps-foundation/scripts/install-foundation-release.sh"
    )
    assert "/releases/" not in foundation[1]
    assert core[1].endswith("source/infra/application/scripts/install-application-release.sh")
    archive = options["env"]["AC_RELEASE_ARCHIVE"]
    assert options == {
        "env": {
            "AC_RELEASE_ID": f"foundation-{HEAD}",
            "AC_RELEASE_ARCHIVE": archive,
            "AC_RELEASE_ARCHIVE_SHA256": runner.archives[archive],
            "AC_INSTALL_SCOPE": "backup",
        },
        "timeout": 900,
        "log": Path(result["log"]),
        "check": False,
    }
    archive_calls = [argv for argv, _ in runner.operations if "archive" in argv]
    assert [argv[-3:] for argv in archive_calls] == [
        [HEAD, "--", "infra/vps-foundation"],
        [HEAD, "--", "infra/application"],
    ]
    entry, deployed = engine.history()
    assert (
        entry.items()
        >= {
            "action": "foundation-backup-install",
            "environment": "staging",
            "sha": HEAD,
            "migration": MIGRATION,
            "result": "success",
            "log": result["log"],
        }.items()
    )
    assert runner.history_at_core == [entry]
    assert deployed["result"] == "success"
    assert not engine.is_paused("staging")


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"exit_code": 9}, "exited with 9"),
        ({"updates_tool": False}, "do not recognise migration"),
        ({"raises": subprocess.TimeoutExpired("bash", 900)}, "timed out"),
    ],
)
def test_failed_install_or_second_check_refuses_core_and_pauses(tmp_path, kwargs, error):
    engine, runner, build = setup(tmp_path, **kwargs)
    with pytest.raises(MODULE.ReleaseError, match=error):
        engine.deploy_core("staging", build)
    assert len(runner.installers()) == 1
    (entry,) = engine.history()
    assert entry["action"] == "foundation-backup-install"
    assert entry["result"] == "failed"
    assert error in entry["error"]

    attempted, attempted_runner, build = setup(tmp_path / "attempt", **kwargs)
    result = attempted.attempt("staging", "core", build, dry_run=False, trigger="auto")
    assert result["result"] == "failed"
    assert len(attempted_runner.installers()) == 1
    assert attempted.is_paused("staging")
    assert attempted.failed_sha("staging", "core") == HEAD
    assert [entry["result"] for entry in attempted.history()] == ["failed", "failed"]


def test_known_head_needs_no_foundation_archive_or_install(tmp_path):
    engine, runner, build = setup(tmp_path)
    foundation_backup_tool(engine, MIGRATION)
    engine.deploy_core("staging", build)
    assert len(runner.installers()) == 1
    assert runner.installers()[0][0][1].endswith("install-application-release.sh")
    assert all(argv[-1] != "infra/vps-foundation" for argv, _ in runner.operations)
    assert engine.history() == []


@pytest.mark.parametrize("known", [True, False])
def test_rollback_only_never_installs_foundation(tmp_path, known):
    engine, runner, build = setup(tmp_path)
    engine.installed_engine = lambda: OUTSIDE
    if known:
        foundation_backup_tool(engine, MIGRATION)
        engine.deploy_core("staging", build, rollback_only=True)
        installer, options = runner.installers()[0]
        assert "/controller/" in installer[1]
        assert options["env"]["AC_CORE_ROLLBACK_ONLY"] == "1"
    else:
        with pytest.raises(MODULE.ReleaseError, match="do not recognise migration"):
            engine.deploy_core("staging", build, rollback_only=True)
        assert runner.installers() == []
    assert all(argv[-1] != "infra/vps-foundation" for argv, _ in runner.operations)
    assert engine.history() == []


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
@pytest.mark.parametrize("dry_run", [True, False])
def test_candidate_cannot_drop_a_running_environment_head(tmp_path, environment, dry_run):
    engine, runner, build = setup(tmp_path, candidate_heads=(MIGRATION,))
    running_core(engine, environment, OLD, PREVIOUS_MIGRATION)
    with pytest.raises(
        MODULE.ReleaseError, match=f"does not recognise migration {PREVIOUS_MIGRATION}"
    ):
        engine.deploy_core("staging", build, dry_run=dry_run)
    assert runner.installers() == []
    assert not engine.paths.backup_tool.exists()
    assert len(engine.history()) == (0 if dry_run else 1)


def test_candidate_must_know_the_build_head(tmp_path):
    engine, runner, build = setup(tmp_path, candidate_heads=(PREVIOUS_MIGRATION,))
    with pytest.raises(MODULE.ReleaseError, match=f"does not recognise migration {MIGRATION}"):
        engine.deploy_core("staging", build)
    assert runner.installers() == []
    assert engine.history()[0]["result"] == "failed"


def test_dry_run_plans_install_without_changing_installed_tool_or_history(tmp_path):
    engine, runner, build = setup(tmp_path)
    foundation_backup_tool(engine, PREVIOUS_MIGRATION)
    before = engine.paths.backup_tool.read_bytes()
    result = engine.deploy_core("staging", build, dry_run=True)
    assert result["dry_run"] is True
    assert result["foundation_backup_install"] == MIGRATION
    assert runner.installers() == []
    assert engine.paths.backup_tool.read_bytes() == before
    assert engine.history() == []
    assert not engine.is_paused("staging")


def test_backup_check_reads_installed_tool_instead_of_foundation_source(tmp_path):
    engine, _, _ = setup(tmp_path)
    source_tool = engine.paths.foundation / "scripts" / "ac-postgres-backup.py"
    source_tool.parent.mkdir(parents=True)
    source_tool.write_text(f'HEAD = "{MIGRATION}"\n')
    bundle = tmp_path / "bundle"
    with pytest.raises(MODULE.ReleaseError, match="do not recognise migration"):
        engine.require_backup_support(bundle)
    foundation_backup_tool(engine, MIGRATION)
    source_tool.write_text(f'HEAD = "{PREVIOUS_MIGRATION}"\n')
    engine.require_backup_support(bundle)


def test_invalid_bundle_does_not_attempt_a_foundation_install(tmp_path):
    engine, runner, build = setup(tmp_path)
    (tmp_path / "bundle" / "release-images.env").write_text("AC_MIGRATION_HEAD=latest\n")
    with pytest.raises(MODULE.ReleaseError, match="no valid AC_MIGRATION_HEAD"):
        engine.deploy_core("staging", build)
    assert runner.operations == []
    assert engine.history() == []
