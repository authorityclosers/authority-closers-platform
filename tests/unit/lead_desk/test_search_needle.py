"""A search's words with one space between them (persona QA, 31 Oct 2026)."""

from ac_platform.lead_desk.store import search_needle


def test_spaces_in_a_search_collapse_to_one() -> None:
    assert search_needle("prasad  pandey") == "%prasad pandey%"
    assert search_needle("  Fictional\tMaple ") == "%Fictional Maple%"


def test_a_long_search_is_cut_to_80_characters() -> None:
    assert len(search_needle("a" * 200)) == 82
