"""The test world's three TEST workspaces (owner, 14 Nov 2026: "create the three TEST workspaces
of the test world… each with an owner and 3–4 sellers, marked as test"), built by
sandbox-organisations.py beside its two sandbox organisations without changing them, and the
same people as the bible's planner (docs/qa/test-world/WORLD.md, scripts/call_testing/world.py)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load(name: str, path: str):  # type: ignore[no-untyped-def]
    found = importlib.util.spec_from_file_location(name, ROOT / path)
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    sys.modules[name] = module
    found.loader.exec_module(module)
    return module


change = _load("sandbox_organisations_world", "scripts/data-changes/sandbox-organisations.py")
world = _load("call_testing_world_for_orgs", "scripts/call_testing/world.py")


def _raw(**overrides: object) -> str:
    body = {
        "command_id": "0b8d1c5c-e213-42a6-ac39-c37d99c7cea4",
        "approver_email": "owner@example.test",
        "issue": "owner, 14 Nov 2026",
        "owner_email": "owner@example.test",
        "admin_email": "coach@example.test",
        "seller_mailbox": "owner@example.test",
        "organisations": ["sahyadri", "suryoday", "kavach"],
        "days": 14,
        "scale": 0.5,
    }
    body.update(overrides)
    return json.dumps(body)


def test_the_three_companies_are_marked_test_with_their_own_managers() -> None:
    assert set(change.WORLD) == {"sahyadri", "suryoday", "kavach"}
    for org in change.WORLD.values():
        assert org.name.startswith("TEST · ")
        assert 3 <= len(org.sellers) <= 4
        assert org.manager is not None and org.manager.alias.startswith("tw.")
        assert all(s.alias.startswith("tw.") for s in org.sellers)
        assert {s.sides for s in org.sellers} <= {"both", "cold", "inbound"}
        assert any(s.sides == "cold" for s in org.sellers)
        assert {source.source for source in org.sources} <= {"meta", "webhook"}
        assert all(item.label.startswith("File: ") for item in org.cold)
        assert org.meeting[2] is None or "example.com" in org.meeting[2]
    assert all(org.manager is None for org in change.ORGS.values())


def test_names_numbers_and_logins_never_collide() -> None:
    every = [*change.ORGS.values(), *change.WORLD.values()]
    assert len({org.name for org in every}) == len(every)
    assert len({org.phones for org in every}) == len(every)
    found = change.logins(change.spec_of(_raw()))
    emails = [email for key in found for email in found[key]]
    assert len(emails) == len(set(emails)) == 4 + 1 + 3 + 1 + 3 + 1
    assert all(e.startswith("owner+tw.") and e.endswith("@example.test") for e in emails)


def test_the_input_takes_the_world_and_the_old_keys_still() -> None:
    got = change.spec_of(_raw())
    assert got["organisations"] == ["sahyadri", "suryoday", "kavach"] and got["days"] == 14
    assert change.spec_of(_raw(organisations=["ac", "cyber"]))["organisations"] == ["ac", "cyber"]
    with pytest.raises(SystemExit) as refused:
        change.spec_of(_raw(organisations=["nowhere"]))
    body = json.loads(str(refused.value))
    assert body["refused"] == "unknown_organisation" and "kavach" in body["known"]


def test_the_same_people_as_the_bibles_planner() -> None:
    for agency in world.AGENCIES:
        org = change.WORLD[agency.key]
        assert org.name == agency.name
        people = {f"{s.first} {s.last}" for s in org.sellers}
        assert people == {s.name for s in agency.sellers}
        assert f"{org.manager.first} {org.manager.last}" == agency.owner.name
