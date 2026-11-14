"""An organisation's analysis time per member (orchestrator, 13 Nov 2026): owners and admins."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from ac_platform.billing.projection import Use
from ac_platform.conversation_intelligence import team_analysis_time as team

NOW = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)


class _Database:
    def __init__(self, member: Any = None, rows: tuple[Any, ...] = ()) -> None:
        self.member = member
        self.rows = rows

    async def scalar(self, statement: Any) -> Any:
        del statement
        return self.member

    async def execute(self, statement: Any) -> Any:
        del statement
        return SimpleNamespace(all=lambda: list(self.rows))


def _member(**values: Any) -> SimpleNamespace:
    return SimpleNamespace(**{"status": "active", "ended_at": None, "role": "owner", **values})


async def test_only_an_active_owner_or_admin_sees_the_team() -> None:
    tenant = uuid4()
    actor = SimpleNamespace(tenant_id=tenant, person_id=uuid4())
    assert await team.manages(_Database(_member()), actor, tenant)  # type: ignore[arg-type]
    assert await team.manages(_Database(_member(role="admin")), actor, tenant)  # type: ignore[arg-type]
    for refused in (_member(role="member"), _member(status="removed"), None):
        assert not await team.manages(_Database(refused), actor, tenant)  # type: ignore[arg-type]
    elsewhere = SimpleNamespace(tenant_id=uuid4(), person_id=actor.person_id)
    assert not await team.manages(_Database(_member()), elsewhere, tenant)  # type: ignore[arg-type]


async def test_each_member_used_by_the_pools_own_rule_most_first() -> None:
    asha, owner, quiet = uuid4(), uuid4(), uuid4()
    uses = {
        # A settled call at its charged seconds and one still holding its reserve.
        asha: [Use("u1", NOW, 600), Use("u2", NOW, 1_200, pending=True)],
        owner: [Use("u3", NOW, 0)],
        quiet: [],
    }

    class _Ledger:
        async def _acquisition_uses(self, tenant_id: Any, condition: Any) -> list[Use]:
            del tenant_id
            return uses[condition.right.value]

    rows = (
        (asha, "member", "Fictional Asha", None),
        (owner, "owner", None, "Fictional"),
        (quiet, "member", None, None),
    )
    people = await team.members_used(
        _Database(rows=rows),  # type: ignore[arg-type]
        _Ledger(),  # type: ignore[arg-type]
        tenant_id=uuid4(),
    )
    assert people == [
        {"person_id": str(asha), "name": "Fictional Asha", "role": "member", "used_seconds": 1_800},
        {"person_id": str(owner), "name": "Fictional", "role": "owner", "used_seconds": 0},
        {"person_id": str(quiet), "name": "Member", "role": "member", "used_seconds": 0},
    ]
