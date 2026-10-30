"""The platform capability data change grants only its listed permissions (30 Oct 2026)."""

import asyncio
import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "grant_platform_access_manage", ROOT / "scripts/data-changes/grant-platform-access-manage.py"
)
assert spec is not None and spec.loader is not None
change = importlib.util.module_from_spec(spec)
sys.modules["grant_platform_access_manage"] = change
spec.loader.exec_module(change)

BASE = [
    "--environment",
    "test",
    "--email",
    "owner@example.test",
    "--command-id",
    str(uuid4()),
    "--approver",
    "owner",
    "--issue",
    "AUT-0000",
    "--reason",
    "Fictional reason",
]


def test_default_stays_platform_access_manage() -> None:
    assert change._parser().parse_args(BASE).permission == "platform_access_manage"


@pytest.mark.parametrize("permission", ["platform_tenants_read", "platform_organisations_manage"])
def test_directory_permissions_are_accepted(permission: str) -> None:
    args = change._parser().parse_args([*BASE, "--permission", permission])
    assert args.permission == permission


@pytest.mark.parametrize(
    "permission", ["platform_billing_manage", "platform_release_manage", "learner_diagnose"]
)
def test_other_permissions_are_refused_by_the_parser(permission: str) -> None:
    with pytest.raises(SystemExit):
        change._parser().parse_args([*BASE, "--permission", permission])


def test_execute_refuses_an_unlisted_permission_before_touching_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(change, "_validate", lambda settings, command: uuid4())

    class NoDatabase:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"database used: {name}")

    with pytest.raises(change.DataChangeRefused):
        asyncio.run(
            change.execute(NoDatabase(), object(), object(), "platform_billing_manage")  # type: ignore[arg-type]
        )


def test_the_manager_check_names_the_access_permission_not_the_requested_one() -> None:
    assert change.MANAGER == "platform_access_manage"
    assert change.PERMISSIONS == (
        "platform_access_manage",
        "platform_tenants_read",
        "platform_organisations_manage",
    )
