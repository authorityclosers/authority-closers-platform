from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.organisations import cli
from ac_platform.organisations.service import MemberResult, OrganisationCommandError


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _Transaction:
        return _Transaction()


class _Engine:
    async def dispose(self) -> None:
        return None


def test_cli_refuses_production_without_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AC_DATABASE_URL", "postgresql+psycopg://unused/unused")
    monkeypatch.setenv("AC_ENVIRONMENT", "production")
    with pytest.raises(OrganisationCommandError, match="allow-production"):
        cli._environment(SimpleNamespace(environment="production", allow_production=False))


def test_cli_refuses_environment_that_does_not_match_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AC_DATABASE_URL", "postgresql+psycopg://unused/unused")
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    with pytest.raises(OrganisationCommandError, match="must match AC_ENVIRONMENT"):
        cli._environment(SimpleNamespace(environment="production", allow_production=True))


@pytest.mark.asyncio
async def test_list_members_cli_masks_email(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant_id = uuid4()
    person_id = uuid4()
    monkeypatch.setenv("AC_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.delenv("AC_ENVIRONMENT", raising=False)
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda **_kwargs: SimpleNamespace(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            release_id="test-release",
            operations_tenant_id=uuid4(),
            public_learner_tenant_id=uuid4(),
        ),
    )
    monkeypatch.setattr(
        "sqlalchemy.ext.asyncio.create_async_engine", lambda *_args, **_kwargs: _Engine()
    )
    monkeypatch.setattr(
        "sqlalchemy.ext.asyncio.async_sessionmaker",
        lambda *_args, **_kwargs: lambda: _Session(),
    )

    class Service:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def list_members(self, _tenant_id):
            return (MemberResult(tenant_id, person_id, "suyash@example.test", "member", "active"),)

    monkeypatch.setattr(cli, "OrganisationService", Service)
    args = cli._parser().parse_args(
        ["list-members", "--environment", "test", "--tenant-id", str(tenant_id)]
    )
    assert await cli._run(args) == 0
    output = capsys.readouterr().out
    assert "suyash@example.test" not in output
    assert "s***@example.test" in output
    assert '"role": "member"' in output
