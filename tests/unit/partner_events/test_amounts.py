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
    is_time_word,
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


# --- Re-review 18 Oct, round 2 (table-driven, the re-review's own phrases) -----------------


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


# --- Check 3, 18 Oct (round 3, table-driven, the check's own phrases) ----------------------


@pytest.mark.parametrize(
    "words",
    [
        # Item 1: Devanagari spellings of "watt".
        "45 प्रति वॉट",
        "45 प्रति वॅट",
        "45 प्रति वॅट जास्त आहे",
        "45 प्रति किलोवॅट",
        # Item 2: Devanagari cost words.
        "रेट 45",
        "दर ४५",
        "भाव 45",
        "खर्च 45",
        "चार्ज 50",
        "शुल्क 50",
        "किंमत 45",
        "कीमत 45",
        "kharcha 45",
        "रेट 45 प्रति वॅट",
        "प्रति वॅट दर ४५",
        "दर ४५ प्रति वॉट",
        "भाव 45 / रेट 45",
        "45 का रेट",
        # Item 3: a per-unit phrase or a rupee word before the number.
        "price per watt is 45",
        "rate per watt 45",
        "per watt 45",
        "price per watt 45 is too high",
        "Rs per watt 45",
        "₹/W 45",
        "per kW 60",
        "प्रति वॅट 45",
        "प्रति वॅट आहे ४५",
        # Item 4: number words.
        "forty five per watt",
        "price is twenty five",
        "पैंतालीस प्रति वॅट",
        "पैंतालीस रुपये प्रति वाट",
        "पस्तीस हजार",
        "pachpan per watt",
        # Item 5: hedges between the cost word and the number.
        "rate approx 45",
        "rate is approx 45",
        "price around 45",
        "price is about 45",
        "दर साधारण ४५",
        "रेट जवळपास 45",
        "रेट लगभग 45",
        # Residual closed: "a" and "prati" before a unit.
        "45 a watt",
        "45 prati watt",
    ],
)
def test_check_3_prices_are_prices(words: str) -> None:
    assert mentions_price(words) is True
    assert mentions_price(words, plain_numbers=False) is True


@pytest.mark.parametrize(
    "words",
    [
        # Round 2 behaviour that check 3 confirmed: these are not prices.
        "5 kW",
        "2 ACs",
        "we can do 5 kW",
        "1 dongle",
        "7 years warranty",
        "Kothrud",
        "tomorrow 11 am",
        "Rupesh will send the quotation",
        "Lakhan will visit the site",
        "लाखन साइट पर आएगा",
        "हजारीबाग से ग्राहक",
        "5 किलोवॅट सिस्टम",
        "५ किलोवॉट",
        "5000 वॅट",
        "price for 2 ACs is high",
        "Will share revised price in 2 days",
        "price is too high",
        "price is around the same",
        # "दर" also means "every": a time word after the number keeps it a count.
        "दर महिना",
        "दर 2 महिन्यांनी सर्विस",
        "दर 3 दिवसांनी फोन",
        "दर सोमवारी कॉल",
        # Per-unit phrases that are not money units.
        "5 units per day",
        "2 kW per AC",
        "per day 5 units",
        "the rate at 2 shops",
    ],
)
def test_check_3_keeps_what_is_not_a_price(words: str) -> None:
    assert mentions_price(words) is False


@pytest.mark.parametrize(
    "words,expected",
    [
        ("5 किलोवॅट", (5, "kW")),
        ("५ किलोवॉट", (5, "kW")),
        ("5000 वॅट", (5, "kW")),
        ("5000 वॉट", (5, "kW")),
        ("पाच किलोवॅट", (5, "kW")),
    ],
)
def test_devanagari_watt_spellings_are_sizes(
    words: str, expected: tuple[int | float | None, str | None]
) -> None:
    assert system_size(words) == expected


@pytest.mark.parametrize(
    "words,expected",
    [
        # The complete 1-99 lists are read exactly.
        ("पैंतालीस हजार", 45_000),
        ("पस्तीस हजार", 35_000),
        ("पंचेचाळीस हजार", 45_000),
        ("pachpan hazaar", 55_000),
        ("chhattis lakh", 3_600_000),
        ("सव्वा पस्तीस लाख", 3_525_000),
        ("निन्यानवे हजार", 99_000),
        ("नव्याण्णव हजार", 99_000),
        ("चौऱ्याहत्तर हजार", 74_000),
        ("चौर्\u200dयाहत्तर हजार", 74_000),  # the same word written with a joiner
        # Everyday spellings stay unread: the amount is None, never a guess.
        ("saath hazaar", None),
        ("tera lakh", None),
        ("sola hazaar", None),
        # "das" was read before round 3 and still is (only the summary mask treats it as a
        # possible surname).
        ("das lakh", 1_000_000),
        # Per-unit prices are never totals.
        ("45 prati watt", None),
        ("45 a watt", None),
    ],
)
def test_amount_inr_reads_the_complete_lists(words: str, expected: int | None) -> None:
    assert amount_inr(words) == expected


@pytest.mark.parametrize(
    "left,right",
    [
        ("पन्द्रह", "पंद्रह"),
        ("किम्मत", "किंमत"),
        ("चौऱ्याहत्तर", "चौर्\u200dयाहत्तर"),
        ("हज़ार", "हजार"),
        ("पाँच", "पांच"),
    ],
)
def test_normalise_folds_devanagari_spellings(left: str, right: str) -> None:
    assert normalise(left) == normalise(right)


@pytest.mark.parametrize(
    "token,expected",
    [
        ("महिन्यांनी", True),
        ("दिवसांत", True),
        ("वाजेपर्यंत", True),
        ("सालों", True),
        ("बजे", True),
        ("days", True),
        ("बजेट", False),
        ("बजाज", False),
        ("दिनेश", False),
        ("वाजवी", False),
        (None, False),
    ],
)
def test_time_words(token: str | None, expected: bool) -> None:
    assert is_time_word(token) is expected
