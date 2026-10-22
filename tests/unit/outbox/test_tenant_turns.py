"""Round-robin claim order across organisations (no database)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from ac_platform.conversation_intelligence.processing_plan import due_plan_statement
from ac_platform.outbox.repository import build_job_claim_statement
from ac_platform.outbox.tenant_turns import MAX_TENANT_TURNS, TenantTurns, turn_order


def _sql(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


def test_least_recently_served_organisation_ranks_first() -> None:
    first, second, third = uuid4(), uuid4(), uuid4()
    turns = TenantTurns()
    assert turns.ranks() == {}

    for tenant_id in (first, second, third, first):
        turns.served(tenant_id)
    turns.served(None)

    assert turns.ranks() == {second: 1, third: 2, first: 3}


def test_forgotten_organisations_rank_with_the_never_served() -> None:
    first, second, third = uuid4(), uuid4(), uuid4()
    turns = TenantTurns(capacity=2)

    for tenant_id in (first, second, third):
        turns.served(tenant_id)

    assert turns.ranks() == {second: 1, third: 2}


@pytest.mark.parametrize("capacity", [0, MAX_TENANT_TURNS + 1, True, 2.0])
def test_turn_capacity_is_bounded(capacity: object) -> None:
    with pytest.raises(ValueError):
        TenantTurns(capacity=capacity)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "ranks",
    [
        {"not-a-uuid": 1},
        {uuid4(): 0},
        {uuid4(): True},
        {uuid4(): index for index in range(1, MAX_TENANT_TURNS + 2)},
    ],
)
def test_turn_order_rejects_unbounded_or_malformed_ranks(ranks: object) -> None:
    with pytest.raises(ValueError):
        turn_order(object(), ranks)  # type: ignore[arg-type]


def test_job_claim_goes_round_robin_only_with_turns() -> None:
    now = datetime(2026, 10, 23, 12, tzinfo=UTC)
    fifo = _sql(build_job_claim_statement(now=now, recovery_generation=3, kinds=("a.v1",)))
    fair = _sql(
        build_job_claim_statement(
            now=now,
            recovery_generation=3,
            kinds=("a.v1",),
            tenant_ranks={uuid4(): 1, uuid4(): 2},
        )
    )

    assert "ORDER BY jobs.available_at ASC, jobs.created_at ASC, jobs.id ASC" in fifo
    # The organisation's turn goes first; each organisation keeps the queue order.
    order = fair[fair.index("ORDER BY") :]
    assert order.startswith("ORDER BY CASE WHEN")
    assert order.count("jobs.tenant_id =") == 2
    assert "END ASC, jobs.available_at ASC, jobs.created_at ASC, jobs.id ASC" in order
    assert fair.rstrip().endswith("FOR UPDATE SKIP LOCKED")
    assert fifo.rstrip().endswith("FOR UPDATE SKIP LOCKED")


def test_plan_checks_go_round_robin_only_with_turns() -> None:
    fifo = _sql(due_plan_statement())
    fair = _sql(due_plan_statement({uuid4(): 1}))

    assert "ORDER BY conversation_processing_plans.next_check_at" in fifo
    order = fair[fair.index("ORDER BY") :]
    assert order.startswith("ORDER BY CASE WHEN")
    assert "conversation_processing_plans.tenant_id =" in order
    assert "END, conversation_processing_plans.next_check_at" in order
