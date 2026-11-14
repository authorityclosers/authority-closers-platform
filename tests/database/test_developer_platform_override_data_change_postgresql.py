"""scripts/data-changes/developer-platform-override.py on PostgreSQL: one workspace's
developer-platform tier set and taken away like Admin's settings save (a new revision and
``economics.settings_saved``), dry run by default, idempotent, nothing else changed, refused
for an unknown workspace or account, audited with the approval. Fictional workspace."""

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
            assert dry["after"] == {"override": "organisation", "overrides": 1, "revision": 1}
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
            assert removed["after"] == {"override": None, "overrides": 0, "revision": 2}
            after, revision = await saved()
            assert revision == 2 and after == before
            assert (await do(apply=True, tier=None))["status"] == "no_op"

            async with setup.sessions() as db:
                events = (
                    await db.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.action == script.SAVED)
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
            assert len(events) == 2
            for event in events:
                assert event.actor_person_id == setup.actor.person_id
                assert event.payload["reason"] == WORDS
                assert event.payload["approval"] == {
                    "approver": "Suyash Kulkarni (owner)",
                    "issue": ISSUE,
                    "data_change": script.DATA_CHANGE,
                    "operator": script.OPERATOR,
                }
            given, taken = (event.payload["new"]["developer_platform"] for event in events)
            assert given["overrides"] == {workspace: "organisation"} and taken["overrides"] == {}
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_the_cli_takes_a_workspace_id_and_one_tier_or_remove() -> None:
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
        "--tenant",
    ]
    workspace = str(uuid4())
    for wrong in (
        [workspace, "--tier", "organisation", "--bogus"],
        [workspace],  # neither --tier nor --remove
        [workspace, "--tier", "organisation", "--remove"],
        [workspace, "--tier", "platinum"],
    ):
        with pytest.raises(SystemExit):
            script.main([*common, *wrong])
    assert script.main([*common, "not-a-workspace", "--tier", "organisation"]) == 2
    with pytest.raises(script.Refused, match="tenant_must_be_a_workspace_id"):
        script.tenant("not-a-workspace")
    assert script.TIERS == tier_policy.TIERS
