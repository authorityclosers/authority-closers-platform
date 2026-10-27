"""fix_next_cli: real use's findings, read inside an environment for the radar's cards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ac_platform.telemetry import fix_next_cli


def test_the_week_against_the_week_before_by_default() -> None:
    arguments = fix_next_cli._arguments(
        ["--database-url-file", "/run/url", "--environment", "production"]
    )
    assert (arguments.window, arguments.limit) == ("7d", 25)
    with pytest.raises(SystemExit):
        fix_next_cli._arguments(
            ["--database-url-file", "/run/url", "--environment", "production", "--window", "1y"]
        )


def test_a_failure_is_one_plain_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "no-such-url"
    code = fix_next_cli.main(["--database-url-file", str(missing), "--environment", "production"])
    assert code == 1
    line = json.loads(capsys.readouterr().out.strip())
    assert line["error"] == "FileNotFoundError"
