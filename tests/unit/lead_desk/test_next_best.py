"""What to do now (work-memory engine, section 6; acceptance 17): explainable, tunable,
deterministic."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from ac_platform.lead_desk.commitments import IST
from ac_platform.lead_desk.next_best import Candidate, rank, score, weights_from

NOW = datetime(2026, 10, 24, 17, 50, tzinfo=IST)


def test_at17_a_late_promise_outranks_a_quiet_hot_lead_and_a_task_for_tomorrow() -> None:
    promised = Candidate(
        "lead-a", "Asha", task_id="t1", due_at=NOW - timedelta(minutes=20), promised=True
    )
    quiet = Candidate("lead-b", "Rohan", quiet_hours=72, rot_hours=24, stage_rank=3, max_rank=6)
    tomorrow = Candidate("lead-c", "Neha", task_id="t3", due_at=NOW + timedelta(days=1))
    ranked = rank([tomorrow, quiet, promised], NOW)
    assert [item.candidate.lead_id for item in ranked] == ["lead-a", "lead-b", "lead-c"]
    assert ranked[0].because == ("promised a call back", "20 min overdue")
    assert ranked[1].because[0] == "quiet 3 d"


def test_someone_just_talked_to_goes_down() -> None:
    fresh = Candidate("a", "A", due_at=NOW - timedelta(minutes=5), talked_minutes_ago=3)
    other = Candidate("b", "B", due_at=NOW - timedelta(minutes=5))
    assert [item.candidate.lead_id for item in rank([fresh, other], NOW)] == ["b", "a"]


def test_weights_are_the_business_s_within_bounds() -> None:
    weights = weights_from({"overdue": 9, "promise": -1, "unknown": 2, "sla": True})
    assert weights["overdue"] == 5.0 and weights["promise"] == 0.0
    assert "unknown" not in weights and weights["sla"] == 2.0
    late = Candidate("a", "A", due_at=NOW - timedelta(minutes=60))
    waiting = Candidate("b", "B", waiting_minutes=30, target_minutes=15)
    assert rank([late, waiting], NOW)[0].candidate.lead_id == "a"
    shifted = weights_from({"overdue": 0.5, "sla": 5})
    assert rank([late, waiting], NOW, shifted)[0].candidate.lead_id == "b"


def test_one_entry_per_lead_and_ties_in_a_fixed_order() -> None:
    a1 = Candidate("a", "A", task_id="1", due_at=NOW + timedelta(minutes=30))
    a2 = Candidate("a", "A", task_id="2", due_at=NOW - timedelta(minutes=30))
    b = Candidate("b", "B", task_id="3", due_at=NOW - timedelta(minutes=30))
    ranked = rank([a1, a2, b], NOW)
    assert [(item.candidate.lead_id, item.candidate.task_id) for item in ranked] == [
        ("a", "2"),
        ("b", "3"),
    ]
    assert rank([b, a2, a1], NOW) == ranked


def test_property_more_overdue_never_ranks_lower() -> None:
    chooser = random.Random(17)  # noqa: S311 (seeded test cases, not security)
    for _ in range(2000):
        minutes = chooser.randrange(-300, 600)
        extra = chooser.randrange(1, 240)
        base = dict(
            lead_id="x",
            lead_name="X",
            promised=chooser.random() < 0.3,
            missed_caller=chooser.random() < 0.2,
            stage_rank=chooser.randrange(0, 6),
            max_rank=6,
        )
        sooner = score(Candidate(due_at=NOW - timedelta(minutes=minutes), **base), NOW)
        later = score(Candidate(due_at=NOW - timedelta(minutes=minutes + extra), **base), NOW)
        assert later.score >= sooner.score
