"""First-response SLA rules: when the clock starts, what stops it."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk import sla

T0 = datetime(2027, 1, 18, 6, 0, tzinfo=UTC)  # a Monday, 11:30 India time
SELLER = uuid4()


@dataclass
class Event:
    lead_id: UUID
    kind: str
    created_at: datetime
    data: dict[str, Any] = field(default_factory=dict)
    actor_person_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)


def test_settings_default_to_off_at_15_minutes() -> None:
    assert sla.read({}) == sla.SlaSettings(on=False, minutes=15, alert_managers=False)
    assert sla.read({"sla": {"on": True, "minutes": 7}}).minutes == 15
    with pytest.raises(ValueError):
        sla.as_config(sla.SlaSettings(on=True, minutes=7, alert_managers=False))
    assert sla.as_config(sla.SlaSettings(on=True, minutes=5, alert_managers=True)) == {
        "on": True,
        "minutes": 5,
        "alert_managers": True,
    }


@pytest.mark.parametrize(
    "kind, data, actor, counts",
    [
        ("result", {"stage": "follow_up"}, SELLER, True),
        ("call", {"via": "phone", "direction": "outgoing"}, SELLER, True),
        ("call", {"via": "phone", "direction": "missed"}, SELLER, False),
        ("message", {"channel": "whatsapp", "via": "cloud"}, SELLER, True),
        ("message", {"channel": "whatsapp", "via": "cloud", "auto": "first_reply"}, None, False),
        ("message", {"channel": "whatsapp", "failed": True}, SELLER, False),
        ("note", {}, SELLER, False),
    ],
)
def test_what_counts_as_a_first_response(
    kind: str, data: dict, actor: UUID | None, counts: bool
) -> None:
    assert sla.responded(kind, data, actor) is counts


def test_outside_work_hours_the_clock_starts_when_work_starts() -> None:
    hours = work_hours.WorkHours((0, 1, 2, 3, 4), time(9, 0), time(18, 0), False)
    night = datetime(2027, 1, 18, 17, 0, tzinfo=UTC)  # 22:30 India time
    assert sla.clock_start(night, hours) == work_hours.next_start(hours, night)
    assert sla.clock_start(T0, hours) == T0
    assert sla.clock_start(night, None) == night


def test_each_arrival_and_reopening_has_its_own_clock() -> None:
    lead = uuid4()
    events = [
        Event(lead, "captured", T0),
        Event(
            lead, "call", T0 + timedelta(minutes=3), {"via": "phone", "direction": "missed"}, SELLER
        ),
        Event(lead, "result", T0 + timedelta(minutes=9), {"stage": "lost"}, SELLER),
        Event(lead, "repeat", T0 + timedelta(days=1), {"reopened": True}),
        Event(other := uuid4(), "captured", T0 + timedelta(minutes=1)),
    ]
    clocks = sla.clocks(events, None)
    assert [(c.lead_id, c.started_at, c.responded_at) for c in clocks] == [
        (lead, T0, T0 + timedelta(minutes=9)),
        (other, T0 + timedelta(minutes=1), None),
        (lead, T0 + timedelta(days=1), None),
    ]


def test_the_phone_alert_carries_ids_only() -> None:
    breach = sla.Breached(uuid4(), uuid4(), [SELLER], ["token"])
    data = sla.alert_data(breach)
    assert data["reason"] == "sla" and data["lead"] == str(breach.lead_id)
    assert set(data) == {"type", "kind", "reason", "lead", "tenant", "alerts", "count"}


def test_the_usual_first_response_is_the_median() -> None:
    seller = sla.SellerSla(SELLER, minutes=[2, 30, 4])
    assert seller.median_minutes == 4
    assert sla.SellerSla(SELLER, minutes=[2, 4]).median_minutes == 3
    assert sla.SellerSla(SELLER).median_minutes is None
