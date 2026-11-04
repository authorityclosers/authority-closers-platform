"""A fictional person joins a sandbox organisation only below Owner (owner, 4 Nov 2026: a
fictional Admin in the dev sandbox, not a second Owner): the input is checked, the sign-in is
a plus-alias of the owner's mailbox, and no password or verifier is ever printed."""

import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load(name: str, file: str):  # type: ignore[no-untyped-def]
    found = importlib.util.spec_from_file_location(name, ROOT / "scripts/data-changes" / file)
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    sys.modules[name] = module
    found.loader.exec_module(module)
    return module


change = _load("sandbox_persona", "sandbox-persona.py")

VERIFIER = "scrypt$ln=15,r=8,p=1$" + "a" * 22 + "$" + "b" * 43


def raw(**overrides: object) -> str:
    base = {
        "command_id": str(uuid4()),
        "approver_email": "owner@example.test",
        "issue": "owner chat 4 Nov 2026",
        "tenant_id": str(uuid4()),
        "email": "Owner+AC.Anjali@example.test",
        "name": "  Anjali   Mehta ",
        "role": "Admin",
        "password_hash": VERIFIER,
    }
    return json.dumps({**base, **overrides})


def test_a_full_input_is_accepted_and_tidied() -> None:
    got = change.spec_of(raw())
    assert got["email"] == "owner+ac.anjali@example.test"
    assert got["name"] == "Anjali Mehta"
    assert got["role"] == "admin"
    assert got["password_hash"] == VERIFIER


def test_an_existing_account_needs_no_verifier() -> None:
    assert change.spec_of(raw(password_hash=None))["password_hash"] is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"role": "owner"}, "role_not_allowed"),
        ({"role": "finance"}, "role_not_allowed"),
        ({"email": "anjali@example.test"}, "email_not_a_plus_alias"),
        ({"email": "owner+anjali"}, "email_not_a_plus_alias"),
        ({"name": "A"}, "name_out_of_range"),
        ({"password_hash": "hunter2"}, "password_hash_not_a_verifier"),
        ({"tenant_id": ""}, "missing_input"),
    ],
)
def test_a_wrong_input_is_refused(overrides: dict[str, object], reason: str) -> None:
    with pytest.raises(SystemExit) as refused:
        change.spec_of(raw(**overrides))
    assert json.loads(str(refused.value))["refused"] == reason


def test_a_refusal_never_echoes_the_verifier() -> None:
    with pytest.raises(SystemExit) as refused:
        change.spec_of(raw(role="owner"))
    assert VERIFIER not in str(refused.value)


def test_emails_are_masked_in_what_it_prints() -> None:
    assert change._mask("owner+ac.anjali@example.test") == "o***@example.test"
    assert change._mask(None) == "[none]"
