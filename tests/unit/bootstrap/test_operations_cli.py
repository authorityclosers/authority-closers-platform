"""Operations-only CLI intent validation and commit-before-summary boundary."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext import asyncio as sqlalchemy_asyncio

from ac_platform.bootstrap import OperationsTenantBootstrapResult, cli


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "AC_ENVIRONMENT",
        "AC_BOOTSTRAP_EMAIL",
        "AC_BOOTSTRAP_TENANT_SLUG",
        "AC_BOOTSTRAP_TENANT_NAME",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AC_DATABASE_URL", "sqlite:///unused-test-fixture")


def arguments(command_id: UUID | None = None) -> list[str]:
    return [
        "--operations-only",
        "--environment",
        "local",
        "--tenant-slug",
        "approved-control",
        "--tenant-name",
        "Approved Control",
        "--command-id",
        str(command_id or uuid4()),
        "--operator-reference",
        "review/approved-operator",
        "--reason",
        "Reviewed empty-environment tenant bootstrap",
    ]


@pytest.mark.parametrize("flag", ["--command-id", "--operator-reference", "--reason"])
def test_cli_requires_each_explicit_operator_intent_before_database(
    flag: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    values = arguments()
    index = values.index(flag)
    del values[index : index + 2]
    monkeypatch.setattr(cli, "Settings", lambda **_: pytest.fail("no settings/database expected"))
    assert cli.main(values) == 2
    result = capsys.readouterr()
    assert flag in result.err
    assert result.out == ""


def test_operations_only_preserves_explicit_production_acknowledgement(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    values = arguments()
    values[values.index("local")] = "production"
    monkeypatch.setattr(cli, "Settings", lambda **_: pytest.fail("no settings/database expected"))
    assert cli.main(values) == 2
    result = capsys.readouterr()
    assert "--allow-production" in result.err
    assert result.out == ""


def test_operations_only_rejects_email_without_exposing_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main([*arguments(), "--email", "private-identity@example.test"]) == 2
    result = capsys.readouterr()
    assert "does not accept an identity email" in result.err
    assert "private-identity" not in result.err
    assert result.out == ""


def test_operator_intent_is_not_silently_ignored_in_other_modes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    values = arguments()
    values[0] = "--public-learner"
    assert cli.main(values) == 2
    result = capsys.readouterr()
    assert "operator intent flags require --operations-only" in result.err
    assert result.out == ""


def test_operations_and_public_learner_modes_are_exclusive() -> None:
    with pytest.raises(SystemExit) as error:
        cli.main([*arguments(), "--public-learner"])
    assert error.value.code == 2


@pytest.mark.parametrize("commit_failure", [False, True])
def test_operation_summary_only_after_commit_and_no_other_service_call(
    commit_failure: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command_id, tenant_id = uuid4(), uuid4()
    events: list[str] = []
    calls: list[dict[str, Any]] = []

    class Transaction:
        async def __aenter__(self) -> None:
            events.append("begin")

        async def __aexit__(self, *_args: object) -> None:
            assert capsys.readouterr().out == ""
            events.append("commit")
            if commit_failure:
                raise SQLAlchemyError("sensitive simulated native failure")

    class Database:
        async def __aenter__(self) -> Database:
            return self

        async def __aexit__(self, *_args: object) -> None:
            events.append("close")

        def begin(self) -> Transaction:
            return Transaction()

    class Engine:
        async def dispose(self) -> None:
            events.append("dispose")

    class Application:
        def __init__(self, database: Database) -> None:
            assert isinstance(database, Database)

        async def bootstrap_operations_tenant(
            self, **kwargs: Any
        ) -> OperationsTenantBootstrapResult:
            calls.append(kwargs)
            return OperationsTenantBootstrapResult(tenant_id, True, False)

    monkeypatch.setattr(cli, "BootstrapApplication", Application)
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda **_: SimpleNamespace(database_url="unused", operations_tenant_id=None),
    )
    monkeypatch.setattr(
        sqlalchemy_asyncio, "create_async_engine", lambda *_args, **_kwargs: Engine()
    )
    monkeypatch.setattr(
        sqlalchemy_asyncio, "async_sessionmaker", lambda *_args, **_kwargs: Database
    )
    assert cli.main(arguments(command_id)) == (2 if commit_failure else 0)
    result = capsys.readouterr()
    assert events == ["begin", "commit", "close", "dispose"]
    assert len(calls) == 1
    assert calls[0] == {
        "command_id": command_id,
        "operator_reference": "review/approved-operator",
        "reason": "Reviewed empty-environment tenant bootstrap",
        "tenant_slug": "approved-control",
        "tenant_name": "Approved Control",
        "operations_tenant_id": None,
    }
    if commit_failure:
        assert result.out == ""
        assert result.err == "bootstrap refused: database operation failed\n"
    else:
        assert json.loads(result.out) == {
            "tenant_id": str(tenant_id),
            "tenant_created": True,
            "replayed": False,
        }
        assert result.err == ""
