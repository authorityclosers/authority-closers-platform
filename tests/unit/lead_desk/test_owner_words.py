"""The lead rules' note in plain words for the bell (persona QA, 31 Oct 2026): never
"(fewest)"; the same words as the web's owner-words.ts, to the seller as "you"."""

from __future__ import annotations

from ac_platform.lead_desk import owner_words


def test_the_rules_notes_read_as_sentences() -> None:
    assert owner_words.note("0 open leads (fewest)") == (
        "Picked automatically because they had the fewest open leads."
    )
    assert owner_words.note("1 open lead") == (
        "Picked automatically because they were the only seller who could take it."
    )
    assert owner_words.note("Speaks Hindi, covers Pune, 2 open leads (fewest)") == (
        "Picked automatically because they speak Hindi, cover Pune and had the fewest open leads."
    )
    assert owner_words.note(
        "Nobody free sells this product, speaks Hindi, 1 open lead (fewest)"
    ) == (
        "Picked automatically because they speak Hindi and had the fewest open leads. "
        "Nobody free sells this product."
    )
    assert owner_words.note("Nobody free speaks Tamil; 3 open leads, the fewest.") == (
        "Picked automatically: nobody free speaks Tamil, so it went to whoever had the fewest "
        "open leads."
    )


def test_the_seller_hears_it_as_you() -> None:
    told = owner_words.note("Speaks Hindi, 2 open leads (fewest)", you=True)
    assert told == "Picked automatically because you speak Hindi and had the fewest open leads."
    assert "(fewest)" not in (told or "")
    assert owner_words.note("No call in 15 minutes. 0 open leads (fewest)", you=True) == (
        "Moved on after 15 min with no call. Picked automatically because you had the "
        "fewest open leads."
    )


def test_the_lead_rules_reasons_never_show_their_shorthand() -> None:
    # Redmi QA on production (14 Nov 2026): "webhook: swamini deshpande (rule 1)".
    reason = "webhook: fictional seller (rule 1)"
    assert owner_words.note(reason, you=True) == "Given to you by your lead rules."
    assert owner_words.note(reason) == "Given to Fictional Seller by lead rule 1."
    assert owner_words.note('Pune; "Yes": Fictional Seller (rule 2)') == (
        "Given to Fictional Seller by lead rule 2."
    )
    assert owner_words.note(
        "Rule 1: Fictional Seller away or at their limit, given by the lead rules"
    ) == ("Given out by the lead rules: the people its rule names were away or full.")
    assert owner_words.note("No routing rule matched; given by the lead rules") == (
        "Given out by the lead rules."
    )
    for told in (owner_words.note(reason, you=True), owner_words.note(reason)):
        assert "webhook" not in (told or "") and "(rule" not in (told or "")


def test_notes_that_read_well_pass_and_nothing_is_none() -> None:
    assert owner_words.note("Moved by Fictional Owner") == "Reassigned by Fictional Owner."
    back = "Returning lead: back to Fictional Seller, who handled it before."
    assert owner_words.note(back) == back
    assert owner_words.note(None) is None
    assert owner_words.note("  ") is None
