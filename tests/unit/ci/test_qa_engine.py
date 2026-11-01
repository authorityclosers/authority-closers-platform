"""The QA robot (scripts/qa-engine): every file parses and the self-test passes.

Also checks that nothing secret is in the folder. Node only: nothing here opens a
browser or talks to a server.
"""

import py_compile
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3] / "scripts" / "qa-engine"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")
SOURCES = sorted(path for path in ROOT.rglob("*.cjs"))


@needs_node
@pytest.mark.parametrize("path", SOURCES, ids=lambda path: str(path.relative_to(ROOT)))
def test_node_file_parses(path: Path) -> None:
    result = subprocess.run(  # noqa: S603
        [NODE, "--check", str(path)], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr


@needs_node
def test_selftest_passes() -> None:
    result = subprocess.run(  # noqa: S603
        [NODE, str(ROOT / "selftest.cjs")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "selftest ok" in result.stdout


def test_matrix_wrapper_compiles(tmp_path: Path) -> None:
    py_compile.compile(str(ROOT / "matrix.py"), cfile=str(tmp_path / "matrix.pyc"), doraise=True)


def test_folder_holds_no_secret() -> None:
    pattern = re.compile(
        r"(password|passwd|secret|api[_-]?key|bearer)\s*[:=]\s*[\"'][^\"']{6,}[\"']",
        re.IGNORECASE,
    )
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in {".cjs", ".py", ".json", ".md"}:
            assert not pattern.search(path.read_text(encoding="utf-8")), path
