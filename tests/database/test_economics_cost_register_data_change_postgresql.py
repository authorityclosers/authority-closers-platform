"""scripts/data-changes/economics-cost-register.py on PostgreSQL: the same revision and audit
event as Admin's "Save the cost register", dry run by default, idempotent, only the register
changes, refused for a bad register or account, audited with the approval. Fictional costs."""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.economics import store
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "economics_cost_register", ROOT / "scripts/data-changes/economics-cost-register.py"
)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script  # its dataclasses look themselves up here
_spec.loader.exec_module(script)

WORDS = "Owner, 30 Oct 2026: yes please do this on your own"
REGISTER = {
    "costs": [
        {
            "key": "agents_plan",
            "vendor": "Fictional AI",
            "label": "Agents plan",
            "category": "ai_subscriptions",
            "centre": "agents",
            "cadence": "monthly",
            "rupees": 20000,
            "allocation": {"rule": "token_burn", "tool": "claude"},
            "source": "invoice",
        },
        {
            "key": "test_phone",
            "vendor": "Fictional shop",
            "label": "Test phone",
            "category": "devices",
            "centre": "sales_xray",
            "cadence": "one_time",
            "rupees": 24000,
            "started": "2026-10-02",
            "allocation": {"rule": "direct", "product": "sales_xray"},
            "source": "estimate",
        },
    ],
    "cost_rules": {"platform_work": "company"},
}


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_the_register_is_saved_like_admin_and_audited_with_the_approval(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with setup.sessions() as db:
                from ac_platform.identity.models import Person

                email = (await db.get(Person, setup.actor.person_id)).email
            ops = setup.prepared.state.tenant_id

            async def do(register: dict[str, Any], *, apply: bool, **changes: Any) -> Any:
                command = script.Command(
                    **{
                        "environment": "test",
                        "control_email": email,
                        "register": register,
                        "approver": "Suyash Kulkarni (owner)",
                        "issue": "orch:costs-20261030:1",
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
            assert revision is None and before["costs"] == []
            dry = await do(REGISTER, apply=False)
            assert dry["status"] == "dry_run" and dry["before"]["costs"] == 0
            assert dry["after"]["costs"] == 2 and dry["after"]["by_category"]["devices"] == 1000
            assert (await saved())[1] is None
            applied = await do(REGISTER, apply=True)
            assert applied["status"] == "applied" and applied["after"]["revision"] == 1
            after, revision = await saved()
            assert revision == 1 and [item["key"] for item in after["costs"]] == [
                "agents_plan",
                "test_phone",
            ]
            assert after["cost_rules"] == {"platform_work": "company"}
            # Everything but the register stays as it was.
            assert {k: v for k, v in after.items() if k not in script.REGISTER_KEYS} == {
                k: v for k, v in before.items() if k not in script.REGISTER_KEYS
            }
            assert (await do(REGISTER, apply=True))["status"] == "no_op"

            people = {
                "key": "people",
                "vendor": "Salaries",
                "label": "All staff",
                "category": "people",
                "centre": "people",
                "cadence": "monthly",
                "rupees": 1,
                "allocation": {"rule": "direct", "product": "company"},
            }
            with pytest.raises(script.Refused, match="register_refused_cost_single"):
                await do({"costs": [people, {**people, "key": "people_two"}]}, apply=True)
            with pytest.raises(script.Refused, match="control_account"):
                await do(REGISTER, apply=True, control_email="someone@example.test")

            async with setup.sessions() as db:
                events = (
                    await db.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.action == script.SAVED)
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
            assert len(events) == 1
            event = events[0]
            assert event.actor_person_id == setup.actor.person_id
            assert event.payload["approval"] == {
                "approver": "Suyash Kulkarni (owner)",
                "issue": "orch:costs-20261030:1",
                "data_change": script.DATA_CHANGE,
                "operator": script.OPERATOR,
            }
            assert event.payload["reason"] == WORDS
            assert event.payload["old"]["costs"] == [] and len(event.payload["new"]["costs"]) == 2
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_the_cli_takes_only_its_own_arguments_and_a_base64_register() -> None:
    with pytest.raises(SystemExit):
        script.main(["--environment", "test", "--bogus"])
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
    assert script.main([*common, "--register-b64", "not base64!"]) == 2
    wrong = base64.b64encode(json.dumps({"fees": {}}).encode()).decode()
    assert script.main([*common, "--register-b64", wrong]) == 2
    with pytest.raises(script.Refused, match="register_holds_costs_and_cost_rules_only"):
        script.decode(wrong)
    good = base64.b64encode(json.dumps(REGISTER).encode()).decode()
    assert script.decode(good) == REGISTER
