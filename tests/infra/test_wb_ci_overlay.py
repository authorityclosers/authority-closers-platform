"""wb-ci overlays the current CI files without changing a file's mode (27 Oct 2026: wb_checks.py was
100755 at HEAD, every request overlaid it as 100644, and the CI prerequisite pin check refused the
mode-only change)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WB_CI = ROOT / "scripts/ci/wb-ci"
GIT = shutil.which("git") or "/usr/bin/git"
BASH = shutil.which("bash") or "/bin/bash"
FILES = ("scripts/ci/wb_checks.py", "scripts/ci/wb_matrix.mjs", "scripts/ci/wb_radar.mjs")

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash and file modes")


def _overlay_code() -> str:
    """wb-ci's own lines, from HEAD's sha to the end of the CI-file loop."""
    text = WB_CI.read_text(encoding="utf-8")
    found = re.search(
        r"^wb_head=\$\(\$G --git-dir=\"\$WB/\.git\" rev-parse HEAD\)\n.*?^done\n",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert found, "wb-ci lost its CI-file overlay"
    return found.group(0)


def _git(*args: str, cwd: Path, env: dict[str, str] | None = None) -> str:
    return subprocess.run(  # noqa: S603 - git on a test-owned repository
        [GIT, *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    ).stdout.strip()


def _write(repo: Path, path: str, text: str, mode: int) -> None:
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    file.chmod(mode)


def test_the_overlay_keeps_the_tested_commits_modes(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    wb = tmp_path / "wb"
    wb.mkdir()
    _git("init", "-q", cwd=wb, env=env)
    _git("config", "core.fileMode", "true", cwd=wb, env=env)
    # The tested commit: wb_checks.py plain, wb_matrix.mjs executable, no wb_radar.mjs.
    _write(wb, FILES[0], "checks\n", 0o644)
    _write(wb, FILES[1], "matrix\n", 0o755)
    _git("add", "-A", cwd=wb, env=env)
    _git("commit", "-q", "-m", "tested", cwd=wb, env=env)
    tested = _git("rev-parse", "HEAD", cwd=wb, env=env)
    # HEAD: wb_checks.py made executable (mode only), wb_matrix.mjs changed and plain, a new file.
    _write(wb, FILES[0], "checks\n", 0o755)
    _write(wb, FILES[1], "matrix, newer\n", 0o644)
    _write(wb, FILES[2], "radar\n", 0o755)
    _git("add", "-A", cwd=wb, env=env)
    _git("commit", "-q", "-m", "head", cwd=wb, env=env)

    bare = tmp_path / "bare.git"
    _git("init", "-q", "--bare", str(bare), cwd=tmp_path, env=env)
    (bare / "objects/info/alternates").write_text(f"{wb}/.git/objects\n", encoding="utf-8")
    index = tmp_path / "index"
    run_env = {**env, "GIT_DIR": str(bare), "GIT_INDEX_FILE": str(index)}
    script = (
        f'G={GIT}\nWB="{wb}"\nsha={tested}\nCI_FILES=({" ".join(FILES)})\n'
        '$G read-tree "$sha"\n' + _overlay_code() + "$G write-tree\n"
    )
    tree = subprocess.run(  # noqa: S603 - wb-ci's own lines on a test-owned repository
        [BASH, "-euo", "pipefail", "-c", script],
        cwd=tmp_path,
        env=run_env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    entries = {
        line.split("\t")[1]: line.split()[0]
        for line in _git("ls-tree", "-r", tree, cwd=tmp_path, env=run_env).splitlines()
    }
    assert entries == {FILES[0]: "100644", FILES[1]: "100755", FILES[2]: "100755"}
    # What the request changes against the tested commit: content and new files, never a mode alone.
    changes = _git("diff-tree", "-r", f"{tested}^{{tree}}", tree, cwd=tmp_path, env=run_env)
    changed = {line.split("\t")[1]: line.split()[:4] for line in changes.splitlines()}
    assert set(changed) == {FILES[1], FILES[2]}
    for old_mode, new_mode, old_blob, new_blob in changed.values():
        assert old_blob != new_blob or old_mode.lstrip(":") == new_mode
