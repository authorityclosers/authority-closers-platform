from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci import committed_snapshot as SNAPSHOT
from tests.unit.ci.test_ac_fast_check import git, write
from tests.unit.ci.test_ac_fast_check import repository as repository


def test_export_ignores_staged_unstaged_and_untracked_source(repository: Path) -> None:
    sha = git(repository, "rev-parse", "HEAD")
    write(repository, "README.md", "staged edit\n")
    git(repository, "add", "README.md")
    write(repository, "README.md", "unstaged edit\n")
    write(repository, "builder.py", "uncommitted file\n")
    before = git(repository, "status", "--porcelain")
    with SNAPSHOT.committed_snapshot(repository, sha) as exported:
        assert (exported.root / "README.md").read_text() == "synthetic fixture\n"
        assert not (exported.root / "builder.py").exists()
        assert not (exported.root / ".git").exists()
        assert exported.unchanged()
        path = exported.root
    assert not path.parent.exists()
    assert git(repository, "status", "--porcelain") == before
    assert (repository / "README.md").read_text() == "unstaged edit\n"


def test_workspace_links_wrappers_and_caches_stay_inside_export(repository: Path) -> None:
    write(repository, "packages/typescript/ui/index.cjs", "module.exports = 'committed';\n")
    write(repository, "apps/sales-xray-web/package.json", '{"name": "fixture"}\n')
    git(repository, "add", "packages", "apps")
    git(repository, "commit", "-m", "workspace fixture")
    source = repository / "apps/sales-xray-web/node_modules"
    (source / "@ac").mkdir(parents=True)
    (source / "@ac/ui").symlink_to(repository / "packages/typescript/ui", target_is_directory=True)
    write(repository, "apps/sales-xray-web/node_modules/.cache/receipt", "builder cache\n")
    wrapper = source / ".bin/tool"
    wrapper.parent.mkdir()
    wrapper.write_text(f"#!/bin/sh\nexec node {repository}/node_modules/tool/index.cjs\n")
    wrapper.chmod(0o755)
    write(repository, "packages/typescript/ui/index.cjs", "module.exports = 'uncommitted';\n")
    with SNAPSHOT.committed_snapshot(repository, "HEAD") as exported:
        modules = exported.root / "apps/sales-xray-web/node_modules"
        linked = modules / "@ac/ui"
        assert linked.resolve() == exported.root / "packages/typescript/ui"
        assert (linked / "index.cjs").read_text() == "module.exports = 'committed';\n"
        assert str(repository) not in (modules / ".bin/tool").read_text()
        assert str(exported.root) in (modules / ".bin/tool").read_text()
        assert (modules / ".bin/tool").stat().st_mode & 0o111
        assert not (modules / ".cache").exists()
        (modules / ".cache").mkdir()
        (modules / ".cache/receipt").write_text("export cache\n")
        assert exported.unchanged()
    assert (source / ".cache/receipt").read_text() == "builder cache\n"
    assert (
        repository / "packages/typescript/ui/index.cjs"
    ).read_text() == "module.exports = 'uncommitted';\n"


def test_nested_pnpm_links_rebase_workspace_without_copying_installed_packages(
    repository: Path,
) -> None:
    write(repository, "packages/typescript/ui/index.cjs", "module.exports = 'committed';\n")
    git(repository, "add", "packages")
    git(repository, "commit", "-m", "workspace fixture")
    installed = repository / "node_modules/.pnpm/tool@1/node_modules"
    write(
        repository,
        "node_modules/.pnpm/tool@1/node_modules/tool/index.cjs",
        "module.exports = require('@ac/ui');\n",
    )
    (installed / "@ac").mkdir()
    (installed / "@ac/ui").symlink_to(
        repository / "packages/typescript/ui", target_is_directory=True
    )
    (repository / "node_modules/tool").symlink_to(installed / "tool", target_is_directory=True)
    with SNAPSHOT.committed_snapshot(repository, "HEAD") as exported:
        modules = exported.root / "node_modules/.pnpm/tool@1/node_modules"
        assert (modules / "@ac/ui").resolve() == exported.root / "packages/typescript/ui"
        assert (modules / "tool").is_symlink()
        assert (modules / "tool").resolve() == installed / "tool"
        assert (exported.root / "node_modules/tool").is_symlink()


def test_installed_workspace_without_committed_source_refuses_export(repository: Path) -> None:
    write(repository, "packages/typescript/untracked/index.cjs", "uncommitted\n")
    modules = repository / "node_modules/@ac"
    modules.mkdir(parents=True)
    (modules / "untracked").symlink_to(
        repository / "packages/typescript/untracked", target_is_directory=True
    )
    with (
        pytest.raises(SNAPSHOT.SnapshotError, match="no committed source"),
        SNAPSHOT.committed_snapshot(repository, "HEAD"),
    ):
        pytest.fail("The uncommitted workspace must never be loaded")


def test_export_attests_source_and_cleans_up_after_a_check_failure(repository: Path) -> None:
    with (
        pytest.raises(RuntimeError, match="synthetic failure"),
        SNAPSHOT.committed_snapshot(repository, "HEAD") as exported,
    ):
        path = exported.root
        (path / "README.md").write_text("changed exported source\n")
        assert not exported.unchanged()
        raise RuntimeError("synthetic failure")
    assert not path.parent.exists()
    assert (repository / "README.md").read_text() == "synthetic fixture\n"


def test_committed_external_source_link_is_refused(repository: Path) -> None:
    outside = repository.parent / (repository.name + "-outside.txt")
    outside.write_text("synthetic external source\n")
    (repository / "outside.txt").symlink_to(outside)
    git(repository, "add", "outside.txt")
    git(repository, "commit", "-m", "unsafe source link fixture")
    with pytest.raises(SNAPSHOT.SnapshotError), SNAPSHOT.committed_snapshot(repository, "HEAD"):
        pytest.fail("External source must never be loaded")


def test_invalid_commit_cannot_create_an_export(repository: Path) -> None:
    with (
        pytest.raises(SNAPSHOT.SnapshotError, match="could not be exported"),
        SNAPSHOT.committed_snapshot(repository, "not-a-commit"),
    ):
        pytest.fail("An invalid commit must never run checks")


def test_source_resolution_hook_is_attested(repository: Path) -> None:
    with SNAPSHOT.committed_snapshot(repository, "HEAD") as exported:
        hook = exported.root / ".ac-fast-node-source.cjs"
        assert exported.unchanged()
        hook.write_text("// changed resolution behavior\n")
        assert not exported.unchanged()
