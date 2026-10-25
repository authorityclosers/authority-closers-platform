"""Distribution of a chosen set of leads by a rule (team engine, docs/product/lead-desk/
team-engine.md, section 1 and scenarios 1 to 4), with seeded property checks."""

from __future__ import annotations

import random
from uuid import UUID, uuid4

import pytest

from ac_platform.lead_desk.distribute import (
    CLOSED,
    LIMIT,
    LeadSpot,
    Seller,
    distribute,
)

A, B, C = (UUID(int=n) for n in (1, 2, 3))


def lead(stage: str = "new", owner: UUID | None = None, **extra: str) -> LeadSpot:
    return LeadSpot(lead_id=uuid4(), stage=stage, owner=owner, **extra)  # type: ignore[arg-type]


def seller(person: UUID, open_leads: int = 0, max_open: int = 500) -> Seller:
    return Seller(person_id=person, open_leads=open_leads, max_open=max_open)


def test_even_spreads_ten_over_three_as_four_three_three() -> None:
    plan = distribute([lead() for _ in range(10)], [seller(A), seller(B), seller(C)], "even")
    assert plan.given == {A: 4, B: 3, C: 3}
    assert len(plan.moves) == 10 and plan.left == {}


def test_a_seller_at_cap_takes_none_and_the_rest_wait() -> None:
    plan = distribute(
        [lead() for _ in range(5)],
        [seller(A, open_leads=10, max_open=10), seller(B, max_open=2)],
        "even",
    )
    assert plan.given == {B: 2}
    assert plan.left == {"everyone_at_cap": 3}


def test_by_source_maps_groups_and_leaves_the_unmapped() -> None:
    leads = [
        *(lead(source="meta") for _ in range(4)),
        *(lead(source="google") for _ in range(3)),
        lead(source="csv"),
    ]
    plan = distribute(
        leads,
        [seller(A), seller(B), seller(C)],
        "by_source",
        groups={"Meta": [A, B], "google": [C]},
    )
    assert plan.given == {A: 2, B: 2, C: 3}
    assert plan.left == {"no_seller_for_it": 1}


def test_closed_leads_never_move() -> None:
    leads = [lead(stage) for stage in sorted(CLOSED)] + [lead()]
    plan = distribute(leads, [seller(A)], "even", spread_all=True)
    assert [move.lead_id for move in plan.moves] == [leads[-1].lead_id]
    assert plan.left == {"closed": 3}


def test_a_lead_already_with_a_chosen_seller_stays_unless_spreading_all() -> None:
    leads = [lead(owner=A) for _ in range(4)]
    kept = distribute(leads, [seller(A, open_leads=4), seller(B)], "even")
    assert kept.moves == () and kept.left == {"already_theirs": 4}
    spread = distribute(leads, [seller(A, open_leads=4), seller(B)], "even", spread_all=True)
    assert spread.given == {A: 2, B: 2}
    # Two stay with A (no move written), two go to B.
    assert sorted(move.to for move in spread.moves) == [B, B]


def test_balanced_lets_the_lighter_seller_catch_up() -> None:
    plan = distribute(
        [lead() for _ in range(6)], [seller(A, open_leads=5), seller(B, open_leads=1)], "balanced"
    )
    assert plan.given == {B: 5, A: 1}


def test_unknown_rule_and_too_many_leads_are_refused() -> None:
    with pytest.raises(ValueError):
        distribute([], [seller(A)], "random")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        distribute([lead() for _ in range(LIMIT + 1)], [seller(A)], "even")


@pytest.mark.parametrize("seed", range(40))
def test_properties_over_random_teams(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - seeded test data, not security
    people = [UUID(int=n) for n in range(1, rng.randint(1, 6) + 1)]
    sellers = [
        seller(person, open_leads=rng.randint(0, 20), max_open=rng.randint(5, 40))
        for person in people
    ]
    stages = ["new", "not_connected", "follow_up", "interested", *sorted(CLOSED)]
    leads = [
        LeadSpot(
            lead_id=uuid4(),
            stage=rng.choice(stages),
            owner=rng.choice([None, None, *people, UUID(int=99)]),
            source=rng.choice(["meta", "google", "csv", None]),
        )
        for _ in range(rng.randint(0, 120))
    ]
    rule = rng.choice(["even", "balanced", "by_source"])
    groups = {"meta": people[:1], "google": people[-2:]}
    spread_all = rng.random() < 0.5
    plan = distribute(leads, sellers, rule, groups=groups, spread_all=spread_all)  # type: ignore[arg-type]

    # Each lead is placed once, or left with a reason.
    moved = [move.lead_id for move in plan.moves]
    assert len(moved) == len(set(moved))
    assert sum(plan.given.values()) + sum(plan.left.values()) == len(leads)
    # No seller goes over their cap.
    holds = {s.person_id: s.open_leads for s in sellers}
    for move in plan.moves:
        holds[move.to] += 1
        if move.previous in holds:
            holds[move.previous] -= 1
    for s in sellers:
        assert holds[s.person_id] <= max(s.max_open, s.open_leads)
    # Closed leads never move.
    closed = {item.lead_id for item in leads if item.stage in CLOSED}
    assert not closed & set(moved)
    # Same input, same plan.
    again = distribute(leads, sellers, rule, groups=groups, spread_all=spread_all)  # type: ignore[arg-type]
    assert again == plan
    # Even: among sellers who never hit their cap, counts differ by one at most.
    if rule == "even" and not plan.left.get("everyone_at_cap"):
        free = [
            plan.given.get(s.person_id, 0)
            for s in sellers
            if s.open_leads + plan.given.get(s.person_id, 0) < s.max_open
        ]
        if len(free) > 1 and sum(plan.given.values()):
            assert max(free) - min(free) <= 1 or min(free) == 0
