"""Strict languages (27 Oct 2026): a workspace can ask that a lead nobody free speaks waits
for a manager, instead of going to the least loaded seller. Made-up people only."""

from __future__ import annotations

from uuid import UUID

from ac_platform.lead_desk.allocation import LeadFacts, RepState, allocate

HINDI = RepState(UUID(int=1), "Fictional Hindi", True, 50, 0, languages=("Hindi",))
ENGLISH = RepState(UUID(int=2), "Fictional English", True, 50, 3, languages=("English",))


def test_preferred_languages_still_give_the_lead_to_someone() -> None:
    decision = allocate(LeadFacts(language="Marathi"), [HINDI, ENGLISH])
    assert decision.person_id == HINDI.person_id
    assert decision.reason.startswith("Nobody free speaks Marathi")
    assert decision.rule == "language_gap"


def test_strict_languages_hold_the_lead_for_a_manager() -> None:
    decision = allocate(LeadFacts(language="Marathi"), [HINDI, ENGLISH], strict_language=True)
    assert decision.person_id is None
    assert decision.reason == "Nobody free speaks Marathi; it waits for a manager."
    # A lead someone speaks is unaffected.
    spoken = allocate(LeadFacts(language="English"), [HINDI, ENGLISH], strict_language=True)
    assert spoken.person_id == ENGLISH.person_id
    # And a lead with no language never waits for this.
    plain = allocate(LeadFacts(), [HINDI, ENGLISH], strict_language=True)
    assert plain.person_id == HINDI.person_id
