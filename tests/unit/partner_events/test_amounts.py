"""Our own reader for amounts, sizes and counts said in a call (fictional phrases)."""

from decimal import Decimal

import pytest

from ac_platform.partner_events.amounts import (
    FRACTION_WORDS,
    HUNDRED_WORDS,
    NUMBER_WORDS,
    amount_inr,
    counts_in,
    gst_basis,
    is_currency,
    mask_amounts,
    mentions_price,
    normalise,
    numbers_in,
    system_size,
)


@pytest.mark.parametrize(
    "words,expected",
    [
        ("3.70 lakh", 370_000),
        ("3.7 L", 370_000),
        ("₹3.7L", 370_000),
        ("Rs. 3,70,000", 370_000),
        ("370000", 370_000),
        ("45k", 45_000),
        ("45 thousand", 45_000),
        ("45000/-", 45_000),
        ("1.2 crore", 12_000_000),
        ("0.5 lakh", 50_000),
        ("3.705 lakh", 370_500),
        ("teen lakh", 300_000),
        ("dhai lakh", 250_000),
        ("तीन लाख", 300_000),
        ("साढ़े तीन लाख", 350_000),
        ("३.७ लाख", 370_000),
        ("दीड लाख", 150_000),
        ("3 lakh 70 thousand", 370_000),
        ("1 crore 20 lakh", 12_000_000),
        ("3.70 lakh plus GST", 370_000),
        ("3 lakh rupees only", 300_000),
        ("twenty five thousand", 25_000),
        ("one lakh twenty thousand", 120_000),
        # Review 18 Oct, item 2: these gave confident wrong amounts; each is read in full.
        ("do lakh pachas hazaar", 250_000),
        ("teen lakh sattar hazaar", 370_000),
        ("दो लाख साठ हजार", 260_000),
        ("पाच लाख पन्नास हजार", 550_000),
        ("paune teen lakh", 275_000),
        ("सवा दो लाख", 225_000),
        ("sawa do lakh", 225_000),
        ("सव्वा दोन लाख", 225_000),
        ("पौने तीन लाख", 275_000),
        ("पावणे तीन लाख", 275_000),
        ("saade teen lakh", 350_000),
        ("साडे तीन लाख", 350_000),
        ("सत्तर हजार", 70_000),
        ("sattar hazaar", 70_000),
        # Ambiguous or only partly read: None, never a guess.
        ("3.70", None),
        ("about 3 to 4", None),
        ("3-4 lakh", None),
        ("3 or 4 lakh", None),
        ("3 lakh 70", None),
        ("70 thousand 3 lakh", None),
        ("2 panels and 45k", None),
        ("five", None),
        ("5 kW", None),
        ("5000 watt", None),
        ("1.234567 lakh", None),
        ("", None),
        ("costly", None),
        ("about 3.5 lakh", None),  # an unread word directly before the number
        ("above a lakh", None),  # a money word no number owns
        ("lakh", None),
        ("dho lakh pachas hazaar", None),  # unread spelling: "lakh" has no number
        ("teen lakh sattarr hazaar", None),  # unread spelling: "hazaar" has no number
        ("saade do lakh", None),  # 2.5 is dhai: a fraction word we do not read
        ("sawa lakh", None),  # a fraction word with no number after it
        ("paune lakh", None),
        ("paanch sau", None),  # hundreds are never read
        ("पाच शे", None),
        ("पाचशे रुपये", None),
        ("five hundred", None),
        ("ek sau bees", None),
        ("सौ", None),
        ("3.5 lakh 20 thousand", None),  # only the last part may have a fraction
        ("2 crore 150 lakh", None),  # a part as big as the unit before it
        ("3 3 lakh", None),
        ("can you do 3 lakh", None),
        ("twenty-five thousand", None),
        ("2 lakh 50", None),  # "do lakh pachas" with no unit: ambiguous
        ("₹500", None),  # a bare number under 1,000 stays empty
        ("2000", None),  # a bare number in the year range may be a year
        ("2026 tak", None),
        ("Rs 2,000", 2_000),
        ("2000 rupees", 2_000),
    ],
)
def test_amount_inr_reads_only_the_words_said(words: str, expected: int | None) -> None:
    assert amount_inr(words) == expected


@pytest.mark.parametrize("word", sorted(NUMBER_WORDS))
def test_every_number_word_reads_with_lakh_and_hazaar(word: str) -> None:
    value = NUMBER_WORDS[word]
    assert amount_inr(f"{word} lakh") == int(value * 100_000)
    assert amount_inr(f"{word} hazaar") == int(value * 1_000)
    assert amount_inr(f"{word} हजार") == int(value * 1_000)
    assert numbers_in(f"{word} saal") == {value}


@pytest.mark.parametrize("word", sorted(FRACTION_WORDS))
def test_every_fraction_word_reads_exactly_or_not_at_all(word: str) -> None:
    step, smallest = FRACTION_WORDS[word]
    assert amount_inr(f"{word} {smallest} lakh") == int((smallest + step) * 100_000)
    assert amount_inr(f"{word} {smallest + 1} hazaar") == int((smallest + 1 + step) * 1_000)
    assert amount_inr(f"{word} lakh") is None
    assert amount_inr(f"{word} 3.5 lakh") is None
    if smallest > 1:
        assert amount_inr(f"{word} {smallest - 1} lakh") is None
        assert numbers_in(f"{word} {smallest - 1}") == set()


@pytest.mark.parametrize("word", sorted(HUNDRED_WORDS))
def test_a_hundred_word_is_never_an_amount_but_is_a_price(word: str) -> None:
    assert amount_inr(f"paanch {word}") is None
    assert amount_inr(f"5 {word}") is None
    assert mentions_price(f"packing 5 {word}") is True


@pytest.mark.parametrize(
    "words,expected",
    [
        ("5 kW", (5, "kW")),
        ("5kw", (5, "kW")),
        ("5  KW", (5, "kW")),
        ("5 k.w.", (5, "kW")),
        ("3.5 kW", (3.5, "kW")),
        ("10 KVA", (10, "kVA")),
        ("5000 watt", (5, "kW")),
        ("1100 VA", (1.1, "kVA")),
        ("five kilowatt", (5, "kW")),
        ("5 kilo watt", (5, "kW")),
        ("paanch kW", (5, "kW")),
        ("5 किलोवाट", (5, "kW")),
        ("5", (5, None)),
        ("twenty five kW", (25, "kW")),
        ("sawa do kW", (2.25, "kW")),
        ("3 to 5 kW", (None, None)),
        ("two 5 kW systems", (None, None)),
        ("a big system", (None, None)),
        ("saade do kW", (None, None)),
        ("", (None, None)),
    ],
)
def test_system_size_reads_quantity_and_unit(
    words: str, expected: tuple[int | float | None, str | None]
) -> None:
    assert system_size(words) == expected


@pytest.mark.parametrize(
    "words,expected",
    [
        ("one dongle", {Decimal(1)}),
        ("2 dongles", {Decimal(2)}),
        ("seven years", {Decimal(7)}),
        ("पांच साल", {Decimal(5)}),
        ("saade teen", {Decimal("3.5")}),
        ("twenty five years", {Decimal(25)}),
        ("a dongle", set()),
        ("saade do", set()),
    ],
)
def test_numbers_in_finds_every_number_said(words: str, expected: set[Decimal]) -> None:
    assert numbers_in(words) == expected


@pytest.mark.parametrize(
    "words,expected",
    [
        ("one dongle", {Decimal(1)}),
        ("packing 500", {Decimal(500)}),  # the add-on cap (100) then refuses it
        ("packing charge 2", set()),
        ("2 hazaar packing", set()),
        ("2 rupaiya", set()),
        ("2 dongles, 500 rate", {Decimal(2)}),
    ],
)
def test_counts_in_skips_numbers_next_to_money_or_cost_words(
    words: str, expected: set[Decimal]
) -> None:
    assert counts_in(words) == expected


@pytest.mark.parametrize(
    "words,plain,expected",
    [
        ("3.70 lakh", True, True),
        ("Rs 500", True, True),
        ("₹ 900", True, True),
        ("45000", True, True),
        ("45k", True, True),
        ("5 kW", True, False),
        ("5000 watt", True, False),
        ("1500 sq ft roof", True, False),
        ("1200 square feet", True, False),
        ("by 2026", True, False),
        ("send the quotation today", True, False),
        ("PuREPower 5", False, False),
        ("PP 5000", False, False),
        ("PP 5000", True, True),
        ("PP 3 lakh", False, True),
        # Review 18 Oct, item 4: these passed as "no price".
        ("above a lakh", True, True),
        ("do lakh", True, True),
        ("sattar hazaar", True, True),
        ("सत्तर हजार", True, True),
        ("packing 500", True, True),
        ("500 rupiya", True, True),
        ("packing ka rupaiya alag", True, True),
        ("एक लाख", True, True),
        ("दहा कोटी", True, True),
        ("five crore", False, True),
        ("lakhs", False, True),
        ("packing charge 50", True, True),
        ("packing cost 50", True, True),
        ("rate 40", True, True),
        ("kimat 90", True, True),
        ("कीमत 90", True, True),
        ("दाम 90", True, True),
        ("किंमत 90", True, True),
        ("पाचशे", True, True),
        ("paanch sau", True, True),
        ("रुपये", True, True),
        ("रूपये", True, True),
        # A cost word with no number, or with a unit figure, is not a price.
        ("price is too high", True, False),
        ("the price for 5 kW is high", True, False),
        ("2 dongles", True, False),
        ("100 panels", True, False),
        ("rupture", True, False),
    ],
)
def test_mentions_price(words: str, plain: bool, expected: bool) -> None:
    assert mentions_price(words, plain_numbers=plain) is expected


@pytest.mark.parametrize(
    "token",
    ["rupees", "rupee", "rupaye", "rupiya", "rupaiya", "rupya", "ruppees", "rs", "inr", "₹",
     "रुपये", "रुपए", "रुपया", "रूपये", "रु"],
)  # fmt: skip
def test_rupee_spellings(token: str) -> None:
    assert is_currency(normalise(token))


@pytest.mark.parametrize(
    "words,expected",
    [
        ("3.7 lakh plus GST", "ex_gst"),
        ("3.7 lakh + GST", "ex_gst"),
        ("3.7 lakh+GST", "ex_gst"),
        ("GST extra", "ex_gst"),
        ("GST excluded", "ex_gst"),
        ("3.7 lakh including GST", "incl_gst"),
        ("inclusive of GST", "incl_gst"),
        ("जीएसटी सहित 3 लाख", "incl_gst"),
        ("जीएसटी अलग", "ex_gst"),
        ("जीएसटी धरून", "incl_gst"),
        ("gst ke saath", "incl_gst"),
        ("3.7 lakh", None),
        ("GST", None),
        ("inclusive of GST, transport extra", None),
        # Whole words only: a cue inside another word is not a cue.
        ("GST extraordinary offer", None),
        ("GSTIN included", None),
        ("incline gst", None),
    ],
)
def test_gst_basis_needs_gst_and_one_clear_cue(words: str, expected: str | None) -> None:
    assert gst_basis(words) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "The customer wants a 5 kW system; budget 3.70 lakh plus GST.",
            "The customer wants a 5 kW system; budget [amount] plus GST.",
        ),
        ("Quoted ₹3.7L, customer asked for Rs. 3,40,000.",
         "Quoted [amount], customer asked for [amount]."),
        ("Teen lakh sattar hazaar rupaye bola.", "[amount] bola."),
        ("ग्राहक का बजट दो लाख साठ हजार है।", "ग्राहक का बजट [amount] है।"),
        ("बजेट पाच लाख पन्नास हजार रुपये.", "बजेट [amount]."),
        ("Paune teen lakh mein deal hogi.", "[amount] mein deal hogi."),
        ("सवा दो लाख तक", "[amount] तक"),
        ("Wants it above a lakh.", "Wants it above [amount]."),
        ("Spent lakhs on inverters.", "Spent [amount] on inverters."),
        ("Packing 500 extra, transport 45k.", "Packing [amount] extra, transport [amount]."),
        ("Packing charge 50, dongle 2.", "Packing charge [amount], dongle 2."),
        ("500 rupiya packing ka.", "[amount] packing ka."),
        ("Between 3 to 4 lakh.", "Between [amount]."),
        ("paanch sau ka packing", "[amount] ka packing"),
        ("पाचशे रुपये", "[amount]"),
        # Unit figures, years, small counts and times stay.
        ("1500 sq ft roof, 5000 watt load, 2 ACs.", "1500 sq ft roof, 5000 watt load, 2 ACs."),
        ("Install by 2026; warranty 5 years.", "Install by 2026; warranty 5 years."),
        ("Call back at 5 pm with the quotation.", "Call back at 5 pm with the quotation."),
        ("Price is too high, compared with an inverter.",
         "Price is too high, compared with an inverter."),
        ("in rupees", "in rupees"),
        ("", ""),
    ],
)  # fmt: skip
def test_mask_amounts_replaces_every_amount(text: str, expected: str) -> None:
    masked = mask_amounts(text)
    assert masked == expected
    assert mask_amounts(masked) == masked  # idempotent
    assert amount_inr(masked) is None


@pytest.mark.parametrize(
    "phrase",
    [
        "do lakh pachas hazaar",
        "teen lakh sattar hazaar",
        "दो लाख साठ हजार",
        "पाच लाख पन्नास हजार",
        "paune teen lakh",
        "सवा दो लाख",
        "above a lakh",
        "do lakh",
        "sattar hazaar",
        "सत्तर हजार",
        "packing 500",
        "500 rupiya",
        "100 rupaiya",
    ],
)
def test_no_review_phrase_survives_the_summary_mask(phrase: str) -> None:
    masked = mask_amounts(f"Customer said {phrase} today.")
    assert not mentions_price(masked)
    assert "[amount]" in masked
