"""Refuse ambiguous processing setup before opening a database connection."""

from argparse import Namespace

import pytest

from ac_platform.conversation_intelligence.processing_cli import (
    CommandError,
    main,
    validate_environment,
)


@pytest.mark.parametrize(
    ("environment", "configured", "allowed", "database", "message"),
    [
        ("production", "production", False, "set", "Production requires"),
        ("staging", "production", False, "set", "must match"),
        ("test", "test", False, "", "explicit AC_DATABASE_URL"),
        ("unknown", "", False, "set", "Unsupported environment"),
    ],
)
def test_environment_refused(monkeypatch, environment, configured, allowed, database, message):
    monkeypatch.setenv("AC_ENVIRONMENT", configured)
    monkeypatch.setenv("AC_DATABASE_URL", database)
    with pytest.raises(CommandError, match=message):
        validate_environment(Namespace(environment=environment, allow_production=allowed))


def test_invalid_argument_is_not_echoed(capsys):
    assert main(["--environment", "test", "--tenant-id", "accidental-sensitive-value"]) == 2
    output = capsys.readouterr()
    assert "accidental-sensitive-value" not in output.err
    assert not output.out
