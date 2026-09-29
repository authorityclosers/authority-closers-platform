"""Canary refusal and disabled paths must not expose secrets or open a database."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ac_platform.conversation_intelligence import canary_cli as cli


def test_http_cannot_mark_canary() -> None:
    root = Path(cli.__file__).parents[1] / "http"
    assert not [p for p in root.rglob("*.py") if "mark_canary_submission" in p.read_text()]


def test_disabled_never_opens_database(monkeypatch, capsys) -> None:
    monkeypatch.setenv("AC_ENVIRONMENT", "development")
    monkeypatch.setenv("AC_DATABASE_URL", "unused-sensitive-connection")
    monkeypatch.setattr(cli, "Settings", lambda **_: SimpleNamespace())
    monkeypatch.setattr(cli, "load_pinned_approval", lambda _: None)
    monkeypatch.setattr(cli, "create_async_engine", lambda *a, **k: pytest.fail("database opened"))
    assert cli.main(["--environment", "development", "--json"]) == 0
    assert '"stage_reached": "disabled"' in capsys.readouterr().out


@pytest.mark.parametrize(
    "args",
    [
        ["--environment", "production"],
        ["--environment", "staging"],
        ["--environment", "development", "--timeout-seconds", "1801"],
        ["--environment", "accidental-sensitive-value"],
    ],
)
def test_refusal_is_generic(monkeypatch, capsys, args) -> None:
    monkeypatch.setenv("AC_ENVIRONMENT", "development")
    monkeypatch.setenv("AC_DATABASE_URL", "unused-sensitive-connection")
    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert not output.out and "sensitive" not in output.err
