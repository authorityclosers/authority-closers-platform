"""Round 6 (check 6 and the coordinator's decision D1-D5, 18 Oct 2026; fictional phrases).

No money amount reaches the partner outside ``mentioned_price``: every check-6 blocker phrase
is dropped from all eight non-price fact types and masked in the summary, and the decision's
rules are pinned table by table.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ac_platform.partner_events.amounts import (
    amount_inr,
    carries_money,
    hundreds_word,
    money_scale,
    normalise,
    numbers_in,
)
from ac_platform.partner_events.summary_mask import mask_numbers, mask_when

NON_PRICE_TYPES = (
    "system_size",
    "product_mention",
    "load",
    "add_on",
    "battery_type",
    "warranty",
    "site",
    "delivery_basis",
)

# --- Check 6 blockers --------------------------------------------------------------------------

# B2: a competitor brand with a bare small number, said in any script ("Tata 42 bol raha
# tha"). "Tata42" and "Tata-42" stay allowed by D1 (one token or a hyphen) and are left out.
CHECK_6_B2 = [
    "Tata 42 bol raha tha", "Tata 42 quote kiya", "Adani 40 offer kar raha hai", "Waaree 45 bola",
    "Luminous 48 hai", "Havells 52 tha", "Tata Power 42", "Tata Power Solar 41",
    "Adani Solar 39 bataya", "Vikram 43 lagaya", "Goldi 38", "Exide 46 chal raha", "Microtek 47",
    "UTL 44", "Servotech 49 hai sir", "TATA 42", "Tata 42.5", "Tata 42, Adani 40",
    "Tata 42 aur Adani 40", "Tata 42 hi hai", "Tata 42 offer", "Tata 42 deal",
    "Tata 42 confirm hua", "Tata 42 bataya tha", "Adani forty", "Tata forty two",
    "Tata forty-two bola", "Waaree pachpan", "Adani chalis bola", "Tata बयालीस", "Tata ४२",
    "Loom Solar 44", "Rayzon 41 bol rahe", "Premier 43 hai", "Tata 42 ka quotation",
    "Tata quotation 42", "Adani 40 se kam", "Tata 42 plus installation", "Adani 40", "Tata 42",
    # Romanised Marathi with "wale" glued on (I4).
    "Tatawale pannas detat", "Tatawale panchechalis detat", "Tatawale bechalis detat",
    "Tatawale chavvechalis detat", "Tatawale ekonpannas detat", "Tatawale pachavanna detat",
    "Tatawale ekasashta detat", "Tatawale panchyahattar detat", "Tatawale navvyannav detat",
    "Tatawale ekkyannav detat",
]  # fmt: skip
# B1: colloquial Marathi "-चं" endings on hundreds and money words.
CHECK_6_B1 = [
    "पंधराशेचं डोंगल", "अडीचशेचं पॅकिंग", "दीड लाखाचं इन्व्हर्टर", "दोन लाखांचं काम",
    "साडेतीन लाखाचं", "दीड हजारचं डोंगल", "दोन हजारचं डोंगल",
]  # fmt: skip
# Majors fixed this round (M2 per-watt with a unit, M4 litres read as lakh, M5 "into").
# "45 by 100 watt" stays a site residual (two sides of an area).
CHECK_6_MAJOR = [
    "45 watt padega", "45 watt ka padega", "45 watt lagega", "45 watt ke hisaab se",
    "45 W hisaab", "45 watt chalega", "45 watt pe final", "45 watt only", "46 watt fix",
    "45 Wp ka", "45 watt peak ka", "forty five watt padega", "45W ka", "45Wp lagega",
    "पैंतालीस वॉट का पड़ेगा", "४५ वॉट का पड़ेगा", "४५ वाट के हिसाब से", "पंचेचाळीस वॅटचे पडतील",
    "४५ वॅटचा पडेल", "४५ वॅटचे लागतील", "४५वॅटचे पडतील", "55 kW ka", "60 kW pe",
    "55 kilowatt ke hisaab se", "पचपन किलोवाट का", "45 watt x 5000 watt",
    "48 watt including structure", "45 वॉट से कम नहीं", "5 years warranty 45 watt", "47 watt",
    "2 AC 1.5 L", "fridge 2.95 L", "1 fridge 3.7 L total", "geyser 1.5 L ka", "TV 1.2 L",
    "2 fans 2 L", "45 into 5", "45 into 5 kW", "50 into 4", "45 * 5",
]  # fmt: skip


@pytest.mark.parametrize("fact_type", NON_PRICE_TYPES)
@pytest.mark.parametrize("words", CHECK_6_B2 + CHECK_6_B1 + CHECK_6_MAJOR)
def test_check_6_money_never_stays_in_another_fact(words: str, fact_type: str) -> None:
    assert carries_money(words, fact_type) is True


@pytest.mark.parametrize(
    "text,expected",
    [
        # B1 in the summary, promise and objection mask.
        ("पंधराशेचं डोंगल", "[n] डोंगल"),
        ("अडीचशेचं पॅकिंग", "[n] पॅकिंग"),
        ("दीड लाखाचं इन्व्हर्टर", "[n] इन्व्हर्टर"),
        ("दोन लाखांचं काम", "[n] काम"),
        ("साडेतीन लाखाचं", "[n]"),
        ("दीड हजारचं डोंगल", "[n] डोंगल"),
        ("दोन हजारचं डोंगल", "[n] डोंगल"),
        # M1, structurally: a number-shaped word before a rate verb or a verb of quoting.
        ("Tata ne bayaalees bola", "Tata ne [n] bola"),
        ("Tata ne pachpun bola", "Tata ne [n] bola"),
        ("pachpun tak chalega", "[n] tak chalega"),
        ("टाटा वाले बयालिस बोले", "टाटा वाले [n] बोले"),
        ("टाटावाले बेचाळिस देतात", "टाटावाले [n] देतात"),
        ("टाटावाले पन्नाश देतात", "टाटावाले [n] देतात"),
        ("उनन्चास तक चलेगा", "[n] तक चलेगा"),
        ("Tatawale chavvechalis detat", "Tatawale [n] detat"),
        # M7: English slang.
        ("fortyish per watt", "[n] per watt"),
        ("five grand", "[n]"),
        # Must stay.
        ("grand total", "grand total"),
        ("Ramesh bola kal aayenge", "Ramesh bola kal aayenge"),
    ],
)
def test_check_6_summary_phrases(text: str, expected: str) -> None:
    assert mask_numbers(text) == expected


# --- D1: product mentions -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "words",
    [
        "PuREPower5", "PuREPower-5", "PuREPower Pro-10", "MC4 connector", "Sungrow SG5",
        "Solis 5G", "Waaree 545 Wp", "Adani 540Wp", "PuREPower 3 kW", "Growatt 5 kW",
        "Tata Power Solar", "Waaree bifacial",
    ],
)  # fmt: skip
def test_d1_model_numbers_written_on_or_hyphenated_stay(words: str) -> None:
    assert carries_money(words, "product_mention") is False


@pytest.mark.parametrize(
    "words",
    [
        # Changed expectation: "PuREPower 5" with a space drops now (accepted by D1).
        "PuREPower 5", "PuREPower 3", "PuREPower Pro 10", "Tata 42", "Tata 42.5", "Adani forty",
        "Tata बयालीस", "Tata ४२", "Tatawale pannas detat", "PuREPower five", "Tata forty-two",
        "Tata-forty", "Tata 45k", "Tata 42wala", "Luminous NXG 1850",
    ],
)  # fmt: skip
def test_d1_free_standing_numbers_and_number_words_drop(words: str) -> None:
    assert carries_money(words, "product_mention") is True


# --- D2: watts and rate verbs -------------------------------------------------------------------


@pytest.mark.parametrize(
    "fact_type,words",
    [
        ("system_size", "5000 watt"), ("system_size", "3000 W"),
        ("product_mention", "Waaree 540 Wp"),
        ("load", "2000 W geyser"), ("load", "500 W microwave"), ("load", "100 watt bulb"),
        ("system_size", "5 kW"), ("system_size", "5 kilo watt"), ("system_size", "पाच किलोवॅट"),
        ("load", "200 वॅटचे दिवे"), ("add_on", "8 panels"), ("load", "2 AC"),
    ],
)  # fmt: skip
def test_d2_watt_sizes_from_100_stay(fact_type: str, words: str) -> None:
    assert carries_money(words, fact_type) is False


@pytest.mark.parametrize("fact_type", NON_PRICE_TYPES)
@pytest.mark.parametrize(
    "words",
    [
        "47 watt", "45 W", "99 Wp", "45W", "forty five watt", "पंचेचाळीस वॅट", "४५ वॉट",
        "8 panels lagenge", "2 AC chalega", "5 kW padega", "25 saal milega", "2 dongle denge",
        "दोन एसी लागतील", "पाच पॅनेल पडतील", "दो एसी लगेंगे", "५ किलोवाट मिलेगा",
        "Tata 540 Wp deta", "3 kW lagta", "2 panels milta", "4 earthing pits padta",
        "पाच किलोवॅट मिळेल", "दोन डोंगल देऊ", "तीन पॅनेल पडतात", "Adani देतात 40",
    ],
)  # fmt: skip
def test_d2_small_watts_and_rate_verbs_drop(words: str, fact_type: str) -> None:
    assert carries_money(words, fact_type) is True


# --- D3: when_text ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        # Kept forms.
        ("kal shaam 5 baje", "kal shaam 5 baje"),
        ("parso 4:30", "parso 4:30"),
        ("Monday 10 am", "Monday 10 am"),
        ("7:30 pm", "7:30 pm"),
        ("5.30 baje", "5.30 baje"),
        ("5pm tomorrow", "5pm tomorrow"),
        ("उद्या 11 वाजता", "उद्या 11 वाजता"),
        ("शुक्रवार 5 बजे", "शुक्रवार 5 बजे"),
        ("25 October", "25 October"),
        ("October 20", "October 20"),
        ("1st November", "1st November"),
        ("10-12 November", "10-12 November"),
        ("३० तारीख", "३० तारीख"),
        ("25 tarikh tak", "25 tarikh tak"),
        ("15 November 2026 tak", "15 November 2026 tak"),
        ("15 Dec 2026", "15 Dec 2026"),
        ("30/10", "30/10"),
        ("30/10/2026", "30/10/2026"),
        # Everything else reads [n] (changed expectations: days, weeks, number words).
        ("kal 5 baje 2.35 final", "kal 5 baje [n] final"),
        ("5 baje 2.95", "5 baje [n]"),
        ("Monday 2.95 pe final", "Monday [n] pe final"),
        ("2.95 tarikh tak", "[n] tarikh tak"),
        ("25 October 2000 dena hai", "25 October [n] dena hai"),
        ("30 November 1999", "30 November [n]"),
        ("1 December 2050 final", "1 December [n] final"),
        ("10 tarikh 10 per unit", "10 tarikh [n] per unit"),
        ("20 October 25000", "20 October [n]"),
        ("November 2026", "November [n]"),
        ("3 din me", "[n] din me"),
        ("2 hafte baad", "[n] hafte baad"),
        ("दोन दिवसांनी", "[n] दिवसांनी"),
        ("paanch baje", "[n] baje"),
        ("15 baje", "[n] baje"),
        ("5.75 baje", "[n] baje"),
        ("45 tarikh", "[n] tarikh"),
        ("2026", "[n]"),
        ("25:00 baje", "[n] baje"),
        ("advance 25000 dene ke baad", "advance [n] dene ke baad"),
    ],
)
def test_d3_when_text_keeps_only_strict_forms(text: str, expected: str) -> None:
    assert mask_when(text) == expected


# --- D4: Marathi spoken endings -----------------------------------------------------------------

_HUNDRED_STEMS = ["पंधरा", "अडीच", "दीड", "साडेसात", "बारा", "सव्वा", "पाच", "दोन", "नऊ", "एक"]
_ENDINGS = ["चं", "चा", "ची", "चे", "च्या", "नं", "ला", "ना", "त", "वर", "साठी", "पर्यंत"]


@pytest.mark.parametrize("ending", _ENDINGS)
@pytest.mark.parametrize("stem", _HUNDRED_STEMS)
def test_d4_hundreds_with_spoken_endings(stem: str, ending: str) -> None:
    word = f"{stem}शे{ending}"
    assert hundreds_word(normalise(word)) is True
    assert mask_numbers(f"{word} डोंगल") == "[n] डोंगल"
    assert carries_money(f"{word} डोंगल", "add_on") is True


@pytest.mark.parametrize(
    "word,scale",
    [
        ("लाखाचं", 100_000), ("लाखांचं", 100_000), ("हजारचं", 1_000), ("हजाराचं", 1_000),
        ("लाखानं", 100_000), ("कोटीचं", 10_000_000), ("lakhachan", 100_000),
    ],
)  # fmt: skip
def test_d4_money_words_with_spoken_endings(word: str, scale: int) -> None:
    assert money_scale(normalise(word)) == scale


@pytest.mark.parametrize("stem", ["पाच", "दहा", "पन्नास", "पंचेचाळीस", "साडेतीन"])
@pytest.mark.parametrize("ending", ["चं", "नं", "ना", "ाचं", "ांचं", "ात"])
def test_d4_number_words_with_spoken_endings(stem: str, ending: str) -> None:
    assert mask_numbers(f"टाटावाले {stem}{ending} देतात") == "टाटावाले [n] देतात"


# --- D5: the rest of check 6 --------------------------------------------------------------------


@pytest.mark.parametrize(
    "fact_type,words",
    [
        # Kept: litres for a whole 10 or more, areas in a site, G+ floors, ordinals in a site,
        # Devanagari codes (EV6b).
        ("load", "250 L fridge"), ("load", "geyser 15 L"), ("load", "200 litre geyser"),
        ("site", "terrace 30 by 40"), ("site", "20x30 terrace"), ("load", "G+2 bungalow"),
        ("site", "G+2"), ("site", "3rd floor"), ("site", "B wing, 4th floor"),
        ("add_on", "2 एमसी4 कनेक्टर"), ("add_on", "2 MC4 connectors"),
    ],
)  # fmt: skip
def test_d5_kept_facts(fact_type: str, words: str) -> None:
    assert carries_money(words, fact_type) is False


@pytest.mark.parametrize(
    "fact_type,words",
    [
        ("load", "30 by 40"), ("site", "2.95 by 1"), ("site", "45 into 5"), ("site", "G+45"),
        ("system_size", "G+2"), ("system_size", "45th"), ("site", "45th wala"),
        ("load", "3 AC 4.5 L"), ("product_mention", "PuREPower 5 kW ka"),
    ],
)  # fmt: skip
def test_d5_dropped_facts(fact_type: str, words: str) -> None:
    assert carries_money(words, fact_type) is True


@pytest.mark.parametrize(
    "words,expected",
    [
        ("साडेतीन लाख", 350_000), ("पावणेतीन लाख", 275_000), ("सव्वादोन लाख", 225_000),
        ("five grand", 5_000),
    ],
)  # fmt: skip
def test_d5_joined_fractions_read(words: str, expected: int) -> None:
    assert amount_inr(words) == expected


def test_d5_joined_fraction_sizes() -> None:
    assert numbers_in("साडेतीन किलोवॅट") == {Decimal("3.5")}
