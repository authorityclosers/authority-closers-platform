"""No limit (owner, 25 Oct 2026): the lead rules and distribution never skip a seller whose
open-lead limit is None, and still skip one at a number."""

from __future__ import annotations

from uuid import uuid4

from ac_platform.lead_desk import allocation
from ac_platform.lead_desk.distribute import LeadSpot, Seller, distribute


def rep(open_leads: int, max_open: int | None) -> allocation.RepState:
    return allocation.RepState(
        person_id=uuid4(),
        name="Fictional Seller",
        available=True,
        max_open=max_open,
        open_leads=open_leads,
        languages=(),
        areas=(),
        interests=(),
        last_assigned_at=None,
    )


def test_the_lead_rules_give_to_a_seller_with_no_limit() -> None:
    lead = allocation.LeadFacts(language=None, city=None, interest=None)
    busy = rep(500, None)
    assert allocation.allocate(lead, [busy]).person_id == busy.person_id
    full = rep(50, 50)
    assert allocation.allocate(lead, [full]).person_id is None


def test_distribution_never_caps_no_limit() -> None:
    free, capped = uuid4(), uuid4()
    leads = [LeadSpot(uuid4(), "new") for _ in range(6)]
    plan = distribute(leads, [Seller(free, 900, None), Seller(capped, 2, 3)], "even")
    assert plan.given == {free: 5, capped: 1}
    assert plan.left == {}
