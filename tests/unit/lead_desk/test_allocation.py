"""Dynamic allocation: fair by rules and load, never random, always with a reason."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ac_platform.lead_desk.allocation import LeadFacts, RepState, allocate

NOW = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)


def rep(name: str, open_leads: int = 0, **kwargs: object) -> RepState:
    values: dict[str, object] = {
        "person_id": uuid4(),
        "name": name,
        "available": True,
        "max_open": 25,
        "open_leads": open_leads,
    }
    values.update(kwargs)
    return RepState(**values)  # type: ignore[arg-type]


def test_fewest_open_leads_wins_and_says_so() -> None:
    a, b = rep("Asha", 3), rep("Ravi", 1)
    decision = allocate(LeadFacts(), [a, b])
    assert decision.person_id == b.person_id
    assert decision.reason == "1 open lead (fewest)"
    assert decision.rule == "rules"


def test_ties_go_to_whoever_waited_longest() -> None:
    a = rep("Asha", 2, last_assigned_at=NOW)
    b = rep("Ravi", 2, last_assigned_at=NOW - timedelta(hours=2))
    assert allocate(LeadFacts(), [a, b]).person_id == b.person_id


def test_language_area_and_product_rules_filter_first() -> None:
    hindi = rep("Asha", 9, languages=("Hindi", "English"), areas=("Pune",), interests=("Solar",))
    tamil = rep("Kumar", 0, languages=("ta",), areas=("Chennai",))
    decision = allocate(LeadFacts(language="Hindi", city="Pune", interest="solar rooftop"), [hindi, tamil])
    assert decision.person_id == hindi.person_id
    assert decision.reason.startswith("Speaks Hindi, covers Pune, sells solar rooftop")


def test_language_codes_and_mixed_values_match() -> None:
    mixed = rep("Mira", languages=("en", "hi", "kn"))
    other = rep("Jo", languages=("ta",))
    assert allocate(LeadFacts(language="hi-mr-en"), [other, mixed]).person_id == mixed.person_id


def test_reps_without_limits_take_anything() -> None:
    open_rep = rep("Any", 0)
    assert allocate(LeadFacts(language="Gujarati", city="Surat"), [open_rep]).person_id == (
        open_rep.person_id
    )


def test_product_then_area_relax_before_language() -> None:
    far = rep("Asha", 0, languages=("Hindi",), areas=("Delhi",), interests=("Insurance",))
    decision = allocate(LeadFacts(language="Hindi", city="Pune", interest="Solar"), [far])
    assert decision.person_id == far.person_id
    assert decision.rule == "relaxed"
    assert decision.reason.startswith("Nobody free covers this area")


def test_language_gap_is_named_not_hidden() -> None:
    only = rep("Kumar", 4, languages=("Tamil",))
    decision = allocate(LeadFacts(language="Bengali"), [only])
    assert decision.person_id == only.person_id
    assert decision.rule == "language_gap"
    assert "Nobody free speaks Bengali" in decision.reason


def test_returning_lead_goes_back_to_its_seller() -> None:
    previous = rep("Asha", 10)
    idle = rep("Ravi", 0)
    decision = allocate(LeadFacts(previous_owner=previous.person_id), [previous, idle])
    assert decision.person_id == previous.person_id
    assert decision.rule == "returning"


def test_away_and_full_reps_are_skipped_and_nobody_means_waiting() -> None:
    away = rep("Asha", 0, available=False)
    full = rep("Ravi", 25)
    decision = allocate(LeadFacts(), [away, full])
    assert decision.person_id is None and decision.rule == "none"
    assert "open-lead limit" in decision.reason
    assert "Nobody is available" in allocate(LeadFacts(), [away]).reason


def test_excluded_owner_never_gets_it_back() -> None:
    owner, other = rep("Asha", 0), rep("Ravi", 5)
    decision = allocate(LeadFacts(exclude=frozenset({owner.person_id})), [owner, other])
    assert decision.person_id == other.person_id


def test_load_spreads_across_a_batch() -> None:
    reps = [rep(name) for name in ("A", "B", "C")]
    counts = {r.person_id: 0 for r in reps}
    for _ in range(30):
        chosen = allocate(LeadFacts(), reps).person_id
        assert chosen is not None
        counts[chosen] += 1
        reps = [
            RepState(
                person_id=r.person_id,
                name=r.name,
                available=True,
                max_open=25,
                open_leads=r.open_leads + (r.person_id == chosen),
                last_assigned_at=NOW if r.person_id == chosen else r.last_assigned_at,
            )
            for r in reps
        ]
    assert sorted(counts.values()) == [10, 10, 10]
