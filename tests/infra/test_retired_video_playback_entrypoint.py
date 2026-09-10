"""The retired proof must remain inert for help, import and every old opt-in.

These execute the real script under side-effect traps; no browser, database or
replacement proof is run. They are executable evidence for retiring the unsafe
existing-tab entry point, not new playback acceptance evidence.
"""

from __future__ import annotations

import builtins
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/verify-local-video-playback.py"


@pytest.fixture
def execute_guarded(monkeypatch, tmp_path):
    code = compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec")
    original_import = builtins.__import__

    def denied(*_args, **_kwargs):
        pytest.fail("The retired entry point attempted an external side effect")

    def guarded_import(name, *args, **kwargs):
        # A help-only shim has no need for any browser/network/process library.
        # Apply this only while executing the script, not pytest's own imports.
        if name not in {"__future__", "sys"}:
            pytest.fail("The retired entry point imported an unexpected dependency")
        return original_import(name, *args, **kwargs)

    def execute(arguments, *, imported=False):
        namespace = {
            "__name__": "retired_video_import_test" if imported else "__main__",
            "__file__": str(SCRIPT),
        }
        with monkeypatch.context() as patch:
            patch.chdir(tmp_path)
            patch.setattr(sys, "argv", [str(SCRIPT), *arguments])
            for name in ("Popen", "run", "call", "check_call", "check_output"):
                patch.setattr(subprocess, name, denied)
            for name in ("socket", "create_connection", "getaddrinfo"):
                patch.setattr(socket, name, denied)
            for name in (
                "system",
                "startfile",
                "fork",
                "posix_spawn",
                "posix_spawnp",
                "spawnl",
                "spawnle",
                "spawnlp",
                "spawnlpe",
                "spawnv",
                "spawnve",
                "spawnvp",
                "spawnvpe",
                "execl",
                "execle",
                "execlp",
                "execlpe",
                "execv",
                "execve",
                "execvp",
                "execvpe",
            ):
                if hasattr(os, name):
                    patch.setattr(os, name, denied)
            # Loading/compilation already happened. Execution needs no file I/O.
            patch.setattr(builtins, "open", denied)
            patch.setattr(os, "open", denied)
            patch.setattr(os, "mkdir", denied)
            patch.setattr(Path, "open", denied)
            patch.setattr(Path, "mkdir", denied)
            patch.setattr(builtins, "__import__", guarded_import)
            try:
                exec(code, namespace)  # noqa: S102 - fixed repo entry point under side-effect traps
            except SystemExit as exit_status:
                return exit_status.code
        return None

    return execute


@pytest.mark.parametrize(
    ("arguments", "expected_status"),
    [
        ([], 0),
        (["--help"], 0),
        (["-h"], 0),
        (["--unknown"], 2),
        (["--run"], 2),
        (["--run-authorized-local-hls-proof"], 2),
        (["--run-authorized-local-renewal-proof"], 2),
        (["--help", "synthetic-private-input-do-not-echo"], 2),
        (["--", "synthetic-private-input-do-not-echo"], 2),
    ],
)
def test_all_cli_paths_are_help_only(execute_guarded, capsys, arguments, expected_status):
    assert execute_guarded(arguments) == expected_status
    output = capsys.readouterr()
    assert "Retired:" in output.out
    assert "scripts/verify-local-adaptive-video.mjs" in output.out
    assert "does not execute or forward arguments" in output.out
    assert "synthetic-private-input-do-not-echo" not in output.out + output.err
    assert output.err == (
        "Retired command: execution arguments are not accepted.\n" if expected_status else ""
    )


def test_import_is_inert_even_with_execution_arguments(execute_guarded, capsys):
    assert execute_guarded(["--run-authorized-local-hls-proof"], imported=True) is None
    output = capsys.readouterr()
    assert output.out == output.err == ""
