from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext import asyncio as sqlalchemy_asyncio

from ac_platform.application.release_identity import ReleaseIdentityError
from ac_platform.bootstrap import cli as cli_module
from ac_platform.bootstrap.cli import main


def test_cli_refuses_production_without_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AC_ENVIRONMENT", raising=False)
    result = main(
        [
            "--environment",
            "production",
            "--email",
            "admin@authorityclosers.com",
            "--tenant-slug",
            "authority-closers",
            "--tenant-name",
            "Authority Closers",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "--allow-production" in captured.err
    assert captured.out == ""


def test_cli_requires_explicit_database_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AC_ENVIRONMENT", raising=False)
    monkeypatch.delenv("AC_DATABASE_URL", raising=False)
    result = main(
        [
            "--environment",
            "staging",
            "--email",
            "admin@authorityclosers.com",
            "--tenant-slug",
            "authority-closers",
            "--tenant-name",
            "Authority Closers",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "AC_DATABASE_URL is required" in captured.err
    assert captured.out == ""


def test_cli_requires_baked_release_binding_before_database_engine_creation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_release_id = "a" * 40
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    monkeypatch.setenv("AC_DATABASE_URL", "postgresql+psycopg://fixture.invalid/database")
    monkeypatch.setattr(
        cli_module,
        "Settings",
        lambda **_kwargs: SimpleNamespace(
            release_id=runtime_release_id,
            database_url="postgresql+psycopg://fixture.invalid/database",
        ),
    )
    observed: list[str] = []

    def reject_fabricated_release(value: str) -> str:
        observed.append(value)
        raise ReleaseIdentityError("fixture baked release mismatch")

    def fail_if_engine_reached(*_args: object, **_kwargs: object) -> object:
        pytest.fail("database engine creation must follow baked release verification")

    monkeypatch.setattr(cli_module, "require_baked_release_id", reject_fabricated_release)
    monkeypatch.setattr(sqlalchemy_asyncio, "create_async_engine", fail_if_engine_reached)

    result = main(
        [
            "--environment",
            "staging",
            "--email",
            "admin@authorityclosers.com",
            "--tenant-slug",
            "authority-closers",
            "--tenant-name",
            "Authority Closers",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert observed == [runtime_release_id]
    assert "fixture baked release mismatch" in captured.err
    assert captured.out == ""
