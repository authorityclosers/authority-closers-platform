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
    number_join,
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


# --- Re-review 18 Oct, round 2 (table-driven, the re-review's own phrases) -----------------


@pytest.mark.parametrize(
    "text,expected",
    [
        # B1: a rupee-signed number is an amount even right before a unit.
        ("₹60,000/kW", "[amount]/kW"),
        ("Price ₹60,000/kW for 5 kW", "Price [amount]/kW for 5 kW"),
        ("₹45/W", "[amount]/W"),
        ("₹ 45 /W", "[amount] /W"),
        ("Rs.45/W", "[amount]/W"),
        ("₹55/Wp", "[amount]/Wp"),
        ("₹45/watt incl GST", "[amount]/watt incl GST"),
        ("₹ 50/Wp", "[amount]/Wp"),
        ("₹50Wp", "[amount]Wp"),
        ("₨45/W", "[amount]/W"),
        ("45 per watt", "[amount] per watt"),
        ("Customer was quoted ₹45/W.", "Customer was quoted [amount]/W."),
        ("₹2.2 lakh/kW", "[amount]/kW"),
        ("₹45 प्रति वाट", "[amount] प्रति वाट"),
        ("rate 8 per unit", "rate [amount] per unit"),
        # M1: Marathi and Hindi money words with case endings, romanised spellings, बजेट.
        ("ग्राहकाचे बजेट साडेतीन लाखांपर्यंत आहे.", "ग्राहकाचे बजेट [amount] आहे."),
        ("तीन लाखांत 5 kW", "[amount] 5 kW"),
        ("सत्तर हजारांचा फरक", "[amount] फरक"),
        ("पाच लाखांचे बजेट", "[amount] बजेट"),
        ("दोन करोडचा प्रकल्प", "[amount] प्रकल्प"),
        ("पाच कोटींचा", "[amount]"),
        ("Budget 3 laakh hai.", "Budget [amount] hai."),
        ("3 hajaar packing", "[amount] packing"),
        ("बजेट 3", "बजेट [amount]"),
        ("साडेतीन लाख", "[amount]"),
        ("सव्वादोन लाख", "[amount]"),
        ("पावणेतीन लाख", "[amount]"),
        # m3: a bare decimal that is not a unit figure.
        ("Quoted 3.70 for the 5 kW system", "Quoted [amount] for the 5 kW system"),
        ("Will pay 3.5 max", "Will pay [amount] max"),
        # m4: a number with a digit-group comma is never a year.
        ("Dongle 1,999 only", "Dongle [amount] only"),
        # m5: no partial masks.
        ("one and a half lakh", "[amount]"),
        ("3 and a half lakh", "[amount]"),
        ("three point seven lakh", "[amount]"),
        ("Rs: 50 packing", "[amount] packing"),
        # m6 (conservative, accepted): a flat or plot number over 100 is masked too.
        ("flat 402, plot 1203", "flat [amount], plot [amount]"),
        # m1: names are not rupees; time words keep their numbers.
        ("Rupali 3 baje call karegi", "Rupali 3 baje call karegi"),
        ("Rupesh will send the quotation", "Rupesh will send the quotation"),
        # M3: a number away from the cost word, or a time figure, stays.
        ("Will share revised price in 2 days", "Will share revised price in 2 days"),
        ("Send price list by 6 pm", "Send price list by 6 pm"),
        ("Price too high; will decide in 2 days", "Price too high; will decide in 2 days"),
        ("Compared the price with 2 other vendors", "Compared the price with 2 other vendors"),
        ("Will send price for 2 ACs", "Will send price for 2 ACs"),
        # Still not masked: unit figures, counts, years, places, half on its own.
        ("2 ACs and 10 panels of 540 W, 150 Ah, 450 units",
         "2 ACs and 10 panels of 540 W, 150 Ah, 450 units"),
        ("5 units per day, 24/7 support", "5 units per day, 24/7 support"),
        ("हजारीबाग site, लाखन will call", "हजारीबाग site, लाखन will call"),
        ("half price", "half price"),
        # Still kept (residual): a bare number from 1900 to 2100 may be a year.
        ("Transport 2000 extra", "Transport 2000 extra"),
    ],
)  # fmt: skip
def test_mask_amounts_round_two(text: str, expected: str) -> None:
    masked = mask_amounts(text)
    assert masked == expected
    assert mask_amounts(masked) == masked


@pytest.mark.parametrize(
    "words,plain,expected",
    [
        # B1 and M1: per-unit prices and Marathi money words are prices.
        ("45 per watt", True, True),
        ("45/W", True, True),
        ("₨45/W", True, True),
        ("ग्राहकाचे बजेट साडेतीन लाखांपर्यंत आहे.", True, True),
        ("तीन लाखांत", True, True),
        ("साडेतीन लाखांपर्यंत", True, True),
        ("सत्तर हजारांचा फरक", True, True),
        ("पाच लाखांचे बजेट", True, True),
        ("हजारों का खर्च", True, True),
        ("3 laakh", True, True),
        ("3 hajaar", True, True),
        ("बजेट 3", True, True),
        ("budget of 3", True, True),
        ("charges of 50 only", True, True),
        # m4: "1,999" is never a year.
        ("Dongle 1,999 only", True, True),
        # M3: price-concern objections and promises with a number elsewhere are not prices.
        ("Will share revised price in 2 days", True, False),
        ("Send price list by 6 pm", True, False),
        ("Price too high; will decide in 2 days", True, False),
        ("Compared the price with 2 other vendors", True, False),
        ("price 3 din mein", True, False),
        ("Will send price for 2 ACs", True, False),
        ("cost of 3 panels", True, False),
        # m1: names are not rupees.
        ("Rupesh will send the quotation", True, False),
        ("Rupali 3 baje call karegi", True, False),
        ("Rupa and Rupinder will visit", True, False),
        # m6 (conservative, accepted): a flat number or a load figure over 100 reads as a price.
        ("flat 402", True, True),
        ("AC of 1500", True, True),
        ("हजारीबाग", True, False),
    ],
)
def test_mentions_price_round_two(words: str, plain: bool, expected: bool) -> None:
    assert mentions_price(words, plain_numbers=plain) is expected


@pytest.mark.parametrize(
    "words,expected",
    [
        # m2: per-unit prices, caps and guesses are never read as totals.
        ("₹60,000 per kW", None),
        ("₹60,000/kW", None),
        ("₹2.2 lakh/kW", None),
        ("₹45/W", None),
        ("60000 each", None),
        ("har kW 60000", None),
        ("4 lakh max", None),
        ("3.5 lakh tak", None),
        ("upto 4 lakh", None),
        ("3 lakh approx", None),
        ("2 lakh more", None),
        ("तीन लाखांत", None),
        ("साडेतीन लाखांपर्यंत", None),
        ("लाखभर", None),
        # M1: case endings and romanised spellings are read where the amount is exact.
        ("पाच लाखांचे", 500_000),
        ("सत्तर हजारांचा", 70_000),
        ("दोन कोटींचा", 20_000_000),
        ("3 laakh", 300_000),
        ("3 hajaar", 3_000),
        # m4: a digit-group comma is never a year.
        ("1,999", 1_999),
        ("2,000", 2_000),
        ("2000", None),
        # Unchanged.
        ("3 lakh rupees only", 300_000),
        ("3.70 lakh plus GST", 370_000),
    ],
)
def test_amount_inr_round_two(words: str, expected: int | None) -> None:
    assert amount_inr(words) == expected


@pytest.mark.parametrize(
    "token", ["rupees", "rupee", "rupaye", "rupiya", "rupaiya", "rupya", "ruppees", "₹", "₨"]
)
def test_rupee_words_are_a_closed_list(token: str) -> None:
    assert is_currency(normalise(token))


@pytest.mark.parametrize("name", ["rupesh", "rupali", "rupa", "rupinder", "rupture"])
def test_names_are_not_rupees(name: str) -> None:
    assert not is_currency(name)


@pytest.mark.parametrize(
    "words,expected",
    [
        # m11: "do" before an English pronoun is the verb, never "two".
        ("do you want 1 dongle", {Decimal(1)}),
        ("do dongle", {Decimal(2)}),
        ("one dongle", {Decimal(1)}),
    ],
)
def test_counts_in_reads_do_as_a_verb_before_a_pronoun(words: str, expected: set[Decimal]) -> None:
    assert counts_in(words) == expected


@pytest.mark.parametrize(
    "left,right,following,expected",
    [
        # Hard: one number, and neither half stands alone.
        ("3", "5", "kw", "hard"),
        ("twenty", "five", "years", "hard"),
        ("sawa", "do", "lakh", "hard"),
        ("सवा", "दो", "लाख", "hard"),
        ("point", "seven", "lakh", "hard"),
        ("do", "lakh", None, "hard"),
        ("paanch", "sau", None, "hard"),
        ("lakh", "70", "thousand", "hard"),
        ("लाख", "पन्नास", "हजार", "hard"),
        # Soft: one number or a range.
        ("lakh", "70", None, "soft"),
        ("lakh", "sattar", "mein", "soft"),
        ("do", "teen", "lakh", "soft"),
        ("four", "five", "years", "soft"),
        # Not joined: ordinary words next to digits, a unit that is not money.
        ("do", "5", "kw", None),
        ("one", "5", "kw", None),
        ("two", "1.5", "ton", None),
        ("lakh", "5", "kw", None),
        ("lakh", "do", None, None),
        ("do", "five", "kw", None),
        ("lakh", "2", "lakh", None),
        (None, "5", "kw", None),
    ],
)
def test_number_join(
    left: str | None, right: str, following: str | None, expected: str | None
) -> None:
    assert number_join(left, right, following) == expected
