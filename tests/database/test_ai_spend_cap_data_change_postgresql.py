"""scripts/data-changes/ai-spend-cap.py on PostgreSQL: the same revision and audit event as
Admin's one-click raise, dry run by default, idempotent, refused outside its own caps and
accounts, audited with the approval. Fictional fixture only."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from ac_platform.ai_spend import policy, store
from ac_platform.audit.models import AuditEvent
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "ai_spend_cap", ROOT / "scripts/data-changes/ai-spend-cap.py"
)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script  # its dataclasses look themselves up here
_spec.loader.exec_module(script)

WORDS = (
    "Owner, 21 Oct 2026: up to Rs 300 to run Brain 4.0 on those calls inside production "
    "(no copying out)"
)


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_a_cap_is_set_like_the_admin_raise_and_audited_with_the_approval(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with setup.sessions() as db:
                from ac_platform.identity.models import Person

                email = (await db.get(Person, setup.actor.person_id)).email
            ops = setup.prepared.state.tenant_id

            async def do(cap: int, *, apply: bool, **changes: Any) -> Any:
                command = script.Command(
                    **{
                        "environment": "test",
                        "control_email": email,
                        "target": "brain4_shadow",
                        "cap_inr": cap,
                        "approver": "Suyash Kulkarni (owner, relayed)",
                        "issue": "brain4-ac-sval",
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

            async def cap() -> int:
                async with setup.sessions() as db:
                    config, _ = await store.read(db, "development")
                return policy.cap_of(config, "brain4_shadow")

            assert await cap() == 0
            dry = await do(300, apply=False)
            assert dry["status"] == "dry_run"
            assert dry["before"]["cap_inr"] == 0 and dry["after"]["cap_inr"] == 300
            assert await cap() == 0
            applied = await do(300, apply=True)
            assert applied["status"] == "applied" and await cap() == 300
            assert (await do(300, apply=True))["status"] == "no_op"
            lowered = await do(0, apply=True)
            assert lowered["status"] == "applied" and await cap() == 0

            with pytest.raises(script.Refused, match="not_an_ai_spend_cap"):
                await do(10, apply=True, target="call_data_fast")
            with pytest.raises(script.Refused, match="cap_out_of_range"):
                await do(policy.MAX_DAILY_INR + 1, apply=True)
            with pytest.raises(script.Refused, match="control_account"):
                await do(10, apply=True, control_email="someone@example.test")

            async with setup.sessions() as db:
                events = (
                    await db.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.action.in_([script.RAISED, script.LOWERED]))
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
            assert [event.action for event in events] == [script.RAISED, script.LOWERED]
            raised = events[0]
            assert raised.actor_person_id == setup.actor.person_id
            assert raised.payload["approval"] == {
                "approver": "Suyash Kulkarni (owner, relayed)",
                "issue": "brain4-ac-sval",
                "data_change": script.DATA_CHANGE,
                "operator": script.OPERATOR,
            }
            assert raised.payload["reason"] == WORDS
            assert raised.payload["old"]["feature_caps_inr"]["brain4_shadow"] == 0
            assert raised.payload["new"]["feature_caps_inr"]["brain4_shadow"] == 300
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_the_cli_takes_only_its_own_arguments() -> None:
    with pytest.raises(SystemExit):
        script.main(["--environment", "test", "--bogus"])
    assert (
        script.main(
            [
                "--environment",
                "test",
                "--control-email",
                "x@y",
                "--target",
                "nope",
                "--cap-inr",
                "1",
                "--approver",
                "a",
                "--issue",
                "i",
                "--reason",
                "r",
            ]
        )
        == 2
    )
