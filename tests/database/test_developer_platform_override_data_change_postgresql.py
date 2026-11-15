"""scripts/data-changes/developer-platform-override.py on PostgreSQL: one workspace's
developer-platform tier set and taken away, and connected apps' writes turned on and off, like
Admin's settings save (a new revision and ``economics.settings_saved``), dry run by default,
idempotent, nothing else changed, refused for an unknown workspace or account or nothing to
change, audited with the approval. Fictional workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.economics import store
from ac_platform.integrations import tier_policy, tiers
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "developer_platform_override", ROOT / "scripts/data-changes/developer-platform-override.py"
)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script  # its dataclasses look themselves up here
_spec.loader.exec_module(script)

WORDS = "Owner, 14 Nov 2026: this is a test environment and we need to do every kind of test"
ISSUE = "orch:api-import-proof-20261114:1"


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_one_workspace_gets_a_tier_and_loses_it_like_an_admin_save(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with setup.sessions() as db:
                from ac_platform.identity.models import Person

                email = (await db.get(Person, setup.actor.person_id)).email
            ops = setup.prepared.state.tenant_id
            workspace = str(ops)

            async def do(*, apply: bool, **changes: Any) -> Any:
                command = script.Command(
                    **{
                        "environment": "test",
                        "control_email": email,
                        "tenant_id": ops,
                        "tier": "organisation",
                        "approver": "Suyash Kulkarni (owner)",
                        "issue": ISSUE,
                        "reason": WORDS,
                        "apply": apply,
                        **changes,
                    }
                )
                async with setup.sessions() as db:
                    transaction = await db.begin()
                    try:
                        result = await script.execute(db, command, operations_tenant_id=ops)
                    except BaseException:
                        await transaction.rollback()
                        raise
                    if apply and result["status"] == "applied":
                        await transaction.commit()
                    else:
                        await transaction.rollback()
                    return result

            async def saved() -> tuple[dict[str, Any], int | None]:
                async with setup.sessions() as db:
                    return await store.read(db)

            before, revision = await saved()
            assert revision is None and before["developer_platform"]["overrides"] == {}
            dry = await do(apply=False)
            assert dry["status"] == "dry_run" and dry["before"]["override"] is None
            assert dry["after"] == {
                "advertise_writes": False,
                "override": "organisation",
                "overrides": 1,
                "revision": 1,
            }
            assert (await saved())[1] is None
            applied = await do(apply=True)
            assert applied["status"] == "applied" and applied["after"]["revision"] == 1
            after, revision = await saved()
            assert revision == 1
            assert after["developer_platform"]["overrides"] == {workspace: "organisation"}
            # Everything but this one override stays as it was.
            unset = {**after["developer_platform"], "overrides": {}}
            assert {**after, "developer_platform": unset} == before
            # The workspace now has the Organisation tier and may make API keys, billing on.
            async with setup.sessions() as db:
                tier = await tiers.workspace_tier(
                    db,
                    tiers.platform_from(after["developer_platform"]),
                    billing_enabled=True,
                    tenant_id=ops,
                    person_id=None,
                    personal=False,
                    now=setup.prepared.state.now,
                )
            assert tier.key == "organisation" and tier.api_keys
            assert (await do(apply=True))["status"] == "no_op"

            with pytest.raises(script.Refused, match="no_such_workspace"):
                await do(apply=True, tenant_id=uuid4())
            with pytest.raises(script.Refused, match="control_account"):
                await do(apply=True, control_email="someone@example.test")

            removed = await do(apply=True, tier=None)
            assert (
                removed["status"] == "applied" and removed["before"]["override"] == "organisation"
            )
            assert removed["after"] == {
                "advertise_writes": False,
                "override": None,
                "overrides": 0,
                "revision": 2,
            }
            after, revision = await saved()
            assert revision == 2 and after == before
            assert (await do(apply=True, tier=None))["status"] == "no_op"

            # Connected apps' writes on, alone: every override and setting stays.
            on = await do(apply=True, tenant_id=None, tier=None, advertise_writes=True)
            assert on["status"] == "applied" and "workspace" not in on
            assert on["before"] == {"revision": 2, "advertise_writes": False, "overrides": 0}
            assert on["after"] == {"advertise_writes": True, "overrides": 0, "revision": 3}
            after, revision = await saved()
            assert revision == 3 and after["developer_platform"]["advertise_writes"] is True
            flag_off = {**after["developer_platform"], "advertise_writes": False}
            assert {**after, "developer_platform": flag_off} == before
            assert (await do(apply=True, tenant_id=None, tier=None, advertise_writes=True))[
                "status"
            ] == "no_op"
            off = await do(apply=True, tenant_id=None, tier=None, advertise_writes=False)
            assert off["status"] == "applied" and off["after"]["advertise_writes"] is False
            after, revision = await saved()
            assert revision == 4 and after == before
            # Both in one run (dry): the tier and the flag.
            both = await do(apply=False, advertise_writes=True)
            assert both["status"] == "dry_run"
            assert both["after"] == {
                "advertise_writes": True,
                "override": "organisation",
                "overrides": 1,
                "revision": 5,
            }
            with pytest.raises(script.Refused, match="nothing_to_change"):
                await do(apply=True, tenant_id=None, tier=None)

            # A scope reaches exactly the named tiers; the others and every limit stay.
            scoped = {"tenant_id": None, "tier": None}
            grant = await do(apply=True, **scoped, grants=(("trial", "leads:notes"),))
            assert grant["status"] == "applied"
            assert "leads:notes" not in grant["before"]["scopes"]["trial"]
            assert "leads:notes" in grant["after"]["scopes"]["trial"]
            after, revision = await saved()
            assert revision == 5
            trial = after["developer_platform"]["tiers"]["trial"]
            assert "leads:notes" in trial["scopes"]
            unchanged = {
                **after["developer_platform"]["tiers"],
                "trial": {
                    **trial,
                    "scopes": before["developer_platform"]["tiers"]["trial"]["scopes"],
                },
            }
            assert unchanged == before["developer_platform"]["tiers"]
            assert (await do(apply=True, **scoped, grants=(("trial", "leads:notes"),)))[
                "status"
            ] == "no_op"
            taken_back = await do(apply=True, **scoped, revokes=(("trial", "leads:notes"),))
            assert taken_back["status"] == "applied"
            after, revision = await saved()
            assert revision == 6 and after == before
            for wrong, code in (
                ((("gold", "leads:notes"),), "tier_is_not"),
                ((("trial", "leads:delete"),), "scope_is_not"),
            ):
                with pytest.raises(script.Refused, match=code):
                    await do(apply=True, **scoped, grants=wrong)
            with pytest.raises(script.Refused, match="granted_and_revoked"):
                await do(
                    apply=True,
                    **scoped,
                    grants=(("trial", "leads:notes"),),
                    revokes=(("trial", "leads:notes"),),
                )

            async with setup.sessions() as db:
                events = (
                    await db.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.action == script.SAVED)
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
            assert len(events) == 6
            for event in events:
                assert event.actor_person_id == setup.actor.person_id
                assert event.payload["reason"] == WORDS
                assert event.payload["approval"] == {
                    "approver": "Suyash Kulkarni (owner)",
                    "issue": ISSUE,
                    "data_change": script.DATA_CHANGE,
                    "operator": script.OPERATOR,
                }
            given, taken, writes_on, writes_off, granted, revoked = (
                event.payload["new"]["developer_platform"] for event in events
            )
            assert "leads:notes" in granted["tiers"]["trial"]["scopes"]
            assert "leads:notes" not in revoked["tiers"]["trial"]["scopes"]
            assert given["overrides"] == {workspace: "organisation"} and taken["overrides"] == {}
            assert writes_on["advertise_writes"] is True and writes_off["advertise_writes"] is False
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_the_cli_takes_a_tenant_with_one_tier_or_remove_and_the_writes_flag() -> None:
    common = [
        "--environment",
        "test",
        "--control-email",
        "x@y",
        "--approver",
        "a",
        "--issue",
        "i",
        "--reason",
        "r",
    ]
    workspace = str(uuid4())
    for wrong in (
        ["--tenant", workspace, "--tier", "organisation", "--bogus"],
        ["--tenant", workspace, "--tier", "organisation", "--remove"],
        ["--tenant", workspace, "--tier", "platinum"],
        ["--advertise-writes", "maybe"],
    ):
        with pytest.raises(SystemExit):
            script.main([*common, *wrong])
    for refused in (
        [],  # nothing to change
        ["--tenant", workspace],  # neither --tier nor --remove
        ["--tier", "organisation"],  # no workspace
        ["--remove", "--advertise-writes", "on"],
        ["--tenant", "not-a-workspace", "--tier", "organisation"],
        ["--grant-scope", "trial"],  # not TIER=SCOPE
        ["--grant-scope", "=leads:notes"],
    ):
        assert script.main([*common, *refused]) == 2
    granting = script.command_from(
        script._parser().parse_args(
            [
                *common,
                "--grant-scope",
                "organisation=leads:stage",
                "--grant-scope",
                " enterprise = leads:stage ",
                "--grant-scope",
                "organisation=leads:stage",
                "--revoke-scope",
                "trial=coaching:read",
            ]
        )
    )
    assert granting.grants == (("organisation", "leads:stage"), ("enterprise", "leads:stage"))
    assert granting.revokes == (("trial", "coaching:read"),)
    parse = script._parser().parse_args
    flag = script.command_from(parse([*common, "--advertise-writes", "on"]))
    assert flag.advertise_writes is True and flag.tenant_id is None and flag.tier is None
    taken = script.command_from(parse([*common, "--tenant", workspace, "--remove"]))
    assert str(taken.tenant_id) == workspace and taken.tier is None
    assert taken.advertise_writes is None
    off = script.command_from(parse([*common, "--advertise-writes", "off"]))
    assert off.advertise_writes is False
    with pytest.raises(script.Refused, match="tenant_must_be_a_workspace_id"):
        script.tenant("not-a-workspace")
    assert script.TIERS == tier_policy.TIERS
