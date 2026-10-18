"""Every number in the event summary reads "[n]" (round 3, fictional phrases).

The word tables are generated from the closed lists, so a word added to a list
is tested in every context below.
"""

from __future__ import annotations

import re

import pytest

from ac_platform.partner_events import number_words as words
from ac_platform.partner_events.amounts import FRACTION_WORDS, HUNDRED_WORDS, MONEY_UNITS
from ac_platform.partner_events.summary_mask import mask_numbers


def _deva(word: str) -> bool:
    return any("ऀ" <= char <= "ॿ" for char in word)


_ALL_0_99 = {
    **words.EN_ONES,
    **words.EN_TENS,
    **words.HI_ROMAN,
    **words.MR_ROMAN,
    **words.HI_DEVA,
    **words.MR_DEVA,
}
# Words that are a number wherever they stand.
_ALWAYS = (
    set(_ALL_0_99)
    | words.EN_DECADES
    | words.EN_ORDINALS
    | words.BIG_WORDS
    | words.FRACTION_PREFIXES
    | set(words.FRACTION_VALUES)
    | set(FRACTION_WORDS)
    | HUNDRED_WORDS
    | (set(MONEY_UNITS) - words.SHORT_UNITS)
) - words.SOFT_WORDS
LATIN_WORDS = sorted(word for word in _ALWAYS if not _deva(word))
DEVA_WORDS = sorted(word for word in _ALWAYS if _deva(word))
EVERY_0_99 = sorted(_ALL_0_99)
_DIGIT = re.compile(r"[\d¼-¾⅐-⅞]")


def _masked(text: str) -> str:
    masked = mask_numbers(text)
    assert mask_numbers(masked) == masked  # idempotent: nothing left to mask
    assert not _DIGIT.search(masked)
    return masked


def test_the_lists_are_complete() -> None:
    for table in (words.HI_DEVA, words.MR_DEVA):
        assert set(table.values()) == set(range(100))
    assert set(words.HI_ROMAN.values()) == set(range(100))
    assert set(words.EN_ONES.values()) | set(words.EN_TENS.values()) == set(range(20)) | {
        20,
        30,
        40,
        50,
        60,
        70,
        80,
        90,
    }
    # The irregulars named in the round 3 brief.
    for word, value in [
        ("पैंतालीस", 45),
        ("पस्तीस", 35),
        ("chhattis", 36),
        ("sattar", 70),
        ("pachas", 50),
        ("forty", 40),
        ("पंचेचाळीस", 45),
        ("चौऱ्याहत्तर", 74),
    ]:
        assert _ALL_0_99[word] == value  # fmt: skip


@pytest.mark.parametrize("word", LATIN_WORDS)
def test_every_latin_number_word_is_masked(word: str) -> None:
    assert _masked(f"Customer said {word} today.") == "Customer said [n] today."
    assert _masked(f"{word.capitalize()}, then the rest.") == "[n], then the rest."
    assert _masked(f"{word.upper()} only") == "[n] only"


@pytest.mark.parametrize("word", DEVA_WORDS)
def test_every_devanagari_number_word_is_masked(word: str) -> None:
    assert _masked(f"ग्राहक म्हणाला {word} आज.") == "ग्राहक म्हणाला [n] आज."
    assert _masked(f"ग्राहक ने {word} कहा।") == "ग्राहक ने [n] कहा।"


@pytest.mark.parametrize("word", EVERY_0_99)
def test_every_0_99_word_with_a_money_word_is_one_mask(word: str) -> None:
    # Everyday spellings too ("do lakh", "saath hazaar", "दो लाख"): next to a money word
    # they are a number.
    assert _masked(f"Budget {word} lakh only.") == "Budget [n] only."
    assert _masked(f"budget {word} hazaar rupaye") == "budget [n]"
    assert _masked(f"बजेट {word} हजार रुपये आहे.") == "बजेट [n] आहे."
    assert _masked(f"₹ {word} लाख") == "[n]"


@pytest.mark.parametrize("tens", sorted(words.EN_TENS))
def test_english_tens_and_ones_are_one_mask(tens: str) -> None:
    for ones in ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine"):
        assert _masked(f"price is {tens} {ones}") == "price is [n]"
        assert _masked(f"price is {tens}-{ones} per watt") == "price is [n] per watt"
        assert _masked(f"{tens} {ones} thousand rupees") == "[n]"
    for ordinal in ("first", "second", "third", "fifth"):
        assert _masked(f"on the {tens} {ordinal} of October") == "on the [n] of October"


@pytest.mark.parametrize("stem", sorted(set(words.MR_DEVA) - words.SOFT_WORDS))
def test_marathi_number_words_with_case_endings(stem: str) -> None:
    for ending in ("ला", "च", "ही", "शे", "पर्यंत", "नंतर", "पेक्षा", "ाच", "ांचा", "ाला"):
        assert _masked(f"ग्राहक {stem}{ending} बोलला") == "ग्राहक [n] बोलला"


@pytest.mark.parametrize("stem", sorted(set(words.HI_DEVA) - words.SOFT_WORDS - {"शून्य"}))
def test_hindi_number_words_with_the_plural(stem: str) -> None:
    assert _masked(f"वे {stem}ों आए") == "वे [n] आए"


@pytest.mark.parametrize("prefix", ["साडे", "साढ़े", "सवा", "सव्वा", "पौने", "पावणे"])
def test_joined_fractions(prefix: str) -> None:
    for number in ("दोन", "तीन", "चार", "पाच", "दो", "पांच", "सात", "दहा", "शे", "तीनशे"):
        assert _masked(f"बजेट {prefix}{number} लाख आहे") == "बजेट [n] आहे"
        assert _masked(f"बजेट {prefix}{number} आहे") == "बजेट [n] आहे"
    assert _masked(f"बजेट {prefix} तीन लाख") == "बजेट [n]"


@pytest.mark.parametrize(
    "text",
    [
        "45", "4.5", "3,70,000", "१२३", "३.५", "٣٤٥", "１２３", "½", "2½", "10:30", "18/10/2026",
        "2026-10-18", "24/7", "+91 98200 00000", "5th", "3rd", "18%", "₹45/W", "₹ 45", "Rs.45",
        "Rs:50", "Rs 45", "INR 370000", "45/-", "45/- only", "5kW", "2.5L", "60k", "45 k", "3BHK",
        "v1.2.3", "COVID-19", "₨45/W", "$45", "₹३,७०,०००/-", "१८ ऑक्टोबर", "5.30pm", "11am",
        "3x", "1.5-2 kW", "0", "000", "3" * 400, "3." * 50,
    ],
)  # fmt: skip
def test_no_digit_survives(text: str) -> None:
    masked = _masked(f"Note: {text} end")
    assert masked.startswith("Note: ") and masked.endswith(" end")


@pytest.mark.parametrize(
    "text,expected",
    [
        # Check 3, items 1-5 (each stayed in the summary in round 2).
        ("45 प्रति वॉट", "[n] प्रति वॉट"),
        ("45 प्रति वॅट जास्त आहे", "[n] प्रति वॅट जास्त आहे"),
        ("रेट 45 प्रति वॅट", "रेट [n] प्रति वॅट"),
        ("प्रति वॅट दर ४५", "प्रति वॅट दर [n]"),
        ("दर ४५ प्रति वॉट", "दर [n] प्रति वॉट"),
        ("भाव 45 / रेट 45", "भाव [n] / रेट [n]"),
        ("दर 45 रुपये", "दर [n]"),
        ("price per watt is 45", "price per watt is [n]"),
        ("rate per watt 45 / per watt 45", "rate per watt [n] / per watt [n]"),
        ("price per watt 45 is too high", "price per watt [n] is too high"),
        ("Rs per watt 45 / ₹/W 45", "Rs per watt [n] / ₹/W [n]"),
        ("forty five per watt", "[n] per watt"),
        ("price is twenty five", "price is [n]"),
        ("पस्तीस हजार", "[n]"),
        ("पैंतालीस रुपये प्रति वाट", "[n] प्रति वाट"),
        ("rate approx 45", "rate approx [n]"),
        ("45 a watt / 45 prati watt", "[n] a watt / [n] prati watt"),
        ("5 किलोवॅट सिस्टम / ५ किलोवॉट", "[n] किलोवॅट सिस्टम / [n] किलोवॉट"),
        # Check 3 residuals now closed.
        ("Transport 2000 extra", "Transport [n] extra"),
        ("I can do 3 lakh final", "I can do [n] final"),
        ("aap teen lakh do", "aap [n] do"),
        ("call at 5.30", "call at [n]"),
        # Check 3 probe 1 (round 2 passes), now with "[n]".
        ("quoted ₹45/W", "quoted [n]"),
        ("₹60,000/kW", "[n]"),
        ("Price ₹60,000/kW for 5 kW", "Price [n] for [n] kW"),
        ("₹ 45 /W", "[n] /W"),
        ("Rs.45/W", "[n]"),
        ("₹45/watt incl GST", "[n] incl GST"),
        ("45 per watt", "[n] per watt"),
        ("₹45 प्रति वाट", "[n] प्रति वाट"),
        ("Rs 3.7 lakh", "[n]"),
        ("साडेतीन लाख", "[n]"),
        ("ग्राहकाचे बजेट साडेतीन लाखांपर्यंत आहे.", "ग्राहकाचे बजेट [n] आहे."),
        ("तीन लाखांत 5 kW", "[n] kW"),
        ("सत्तर हजारांचा फरक", "[n] फरक"),
        ("पाच लाखांचे बजेट", "[n] बजेट"),
        ("budget is 2.5 L", "budget is [n]"),
        ("price 3,70,000", "price [n]"),
        ("3 laakh / 3 hajaar", "[n] / [n]"),
        ("Rs: 50 packing", "[n] packing"),
        ("one and a half lakh", "[n]"),
        ("3 and a half lakh", "[n]"),
        ("three point seven lakh", "[n]"),
        ("Quoted 3.70 for the 5 kW system", "Quoted [n] for the [n] kW system"),
        ("Will pay 3.5 max", "Will pay [n] max"),
        ("Dongle 1,999 only", "Dongle [n] only"),
        ("teen lakh sattar hazaar", "[n]"),
        ("दो लाख साठ हजार", "[n]"),
        ("सव्वादोन लाख / पावणेतीन लाख", "[n] / [n]"),
        ("३.५ लाख रुपये", "[n]"),
        ("₹ ३,७०,०००/-", "[n]"),
        ("₹2.2 lakh/kW", "[n]/kW"),
        ("दोन कोटींचा प्रकल्प", "[n] प्रकल्प"),
        ("3 lakh 70 thousand", "[n]"),
        ("above a lakh", "above [n]"),
        ("Rs45 / 45/- per watt", "[n] / [n] per watt"),
        ("rupees forty five per watt", "[n] per watt"),
        ("3-4 lakh", "[n]"),
        ("Between 3 to 4 lakh.", "Between [n] to [n]."),
        ("packing charge 50 / बजेट 3", "packing charge [n] / बजेट [n]"),
        ("INR 370000 / 45 rs per watt", "[n] / [n] per watt"),
        ("4 lakh max / लाखभर रुपये / 60000 each", "[n] max / [n] / [n] each"),
        ("paune teen lakh / Rs 3 lakh 70", "[n] / [n]"),
        ("₹45/W and 3.7 lakh for 5 kW; 2 ACs", "[n] and [n] for [n] kW; [n] ACs"),
        ("Teen lakh sattar hazaar rupaye bola.", "[n] bola."),
        ("Spent lakhs on inverters.", "Spent [n] on inverters."),
        ("paanch sau ka packing / पाचशे रुपये", "[n] ka packing / [n]"),
        ("सवा दो लाख तक", "[n] तक"),
        # Sizes, counts, years and times go too; they arrive as facts.
        ("we can do 5 kW", "we can do [n] kW"),
        ("2 ACs and 10 panels of 540 W, 150 Ah", "[n] ACs and [n] panels of [n] W, [n] Ah"),
        ("1500 sq ft roof, installed in 2026", "[n] sq ft roof, installed in [n]"),
        ("3BHK flat in Kothrud", "[n] flat in Kothrud"),
        ("send quotation tomorrow 11 am", "send quotation tomorrow [n] am"),
        ("Will share revised price in 2 days", "Will share revised price in [n] days"),
        ("two 1.5 ton ACs, 25 years warranty", "[n] ton ACs, [n] years warranty"),
        ("Rupali 3 baje call karegi; 3 वाजता फोन करणार",
         "Rupali [n] baje call karegi; [n] वाजता फोन करणार"),
        ("one dongle, 1 dongle, do dongle", "[n] dongle, [n] dongle, do dongle"),
        ("दो दिन में; do din mein; दोन दिवसांत", "[n] दिन में; [n] din mein; [n] दिवसांत"),
        ("18 Oct 2026, the twenty first", "[n] Oct [n], the [n]"),
        # Names, places and everyday words stay.
        ("Rupesh will send the quotation", "Rupesh will send the quotation"),
        ("Lakhan will visit the site; लाखन साइट पर आएगा",
         "Lakhan will visit the site; लाखन साइट पर आएगा"),
        ("हजारीबाग से ग्राहक; Anna Hazare and हजारे", "हजारीबाग से ग्राहक; Anna Hazare and हजारे"),
        ("Rupa and Rupinder from Lakhani Traders", "Rupa and Rupinder from Lakhani Traders"),
        ("Price is too high, compared with an inverter.",
         "Price is too high, compared with an inverter."),
        ("in rupees", "in rupees"),
        ("", ""),
    ],
)  # fmt: skip
def test_check_3_phrases(text: str, expected: str) -> None:
    assert _masked(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # Words that contain a number word: whole words only.
        "Often someone attended; the tone was honest, the phone is done and gone.",
        "Money, weight, height, tenant, tender, content, kitten, oneself, anyone, everyone.",
        "Pointer, pointless, halfway, headquarters, teenager, charger, quartz, sevens? no.",
        "Lakhan, Lakhani, Lakhpat, Crorepati, Hazare, Hazarika, Rupesh, Rupali, Rupinder.",
        "Kothrud, Baner, Satara, Baramati, Dongle, Dosti, Ekta, Saathi, Teenu.",
        "हजारीबाग, हजारे, लाखन, लाखणी, सातारा, बारामती, एकदम, एकूण, एकता, एकत्र, साठी, साठा.",
        "साठवण, साठे, चारचाकी, विचार, आठवडा, आठवण, सवाल, सवाई, नौकरी, सौदा, दसरा, तीसरा.",
        "आधार कार्ड, आधीच, आधी कॉल केला, पाव भाजी, दोन्ही, दोघे, सहाय्य, दहावी, करोड़पति.",
        "अरब देश, नव वर्ष, साडेसाती, सवालाचे उत्तर, एकदा, दुप्पट.",
        "Customer asked in rupees; the price is too high; the rate card is old.",
        "The point is the price, and a quarterly plan.",
        # Everyday words that are also number words, used as everyday words.
        "Do you want the dongle? We can do it. I do not know. Let's do the visit.",
        "No one was home; the one with lithium; this one or that one; one another.",
        "GST ke saath; mere saath; Mr Das and Ms Dus; a tin roof; she sat down.",
        "कोटेशन भेज दो। मुझे दो। बता दो।",
        "Don't worry, Don will call.",
        "first call, second visit, third time",
    ],
)  # fmt: skip
def test_ordinary_words_are_untouched(text: str) -> None:
    assert mask_numbers(text) == text


@pytest.mark.parametrize(
    "text,expected",
    [
        # "do": the verb after a modal or pronoun, or before a pronoun; a number next to a
        # number word, a money word, a rupee word or a time word.
        ("we can do five kW", "we can do [n] kW"),
        ("will do 3 lakh", "will do [n]"),
        ("do teen lakh", "[n]"),
        ("sawa do lakh", "[n]"),
        ("do rupaye", "[n]"),
        ("do baje call", "[n] baje call"),
        ("teen lakh do", "[n] do"),
        ("ek do din", "[n] din"),
        # "one": a pronoun after the, this, no ...; a number elsewhere.
        ("the one lakh offer", "the [n] offer"),
        ("this one and a half lakh", "this [n]"),
        ("one of the two quotes", "[n] of the [n] quotes"),
        ("One dongle", "[n] dongle"),
        # "दो": the verb after a verb stem or at the end of a sentence; a number elsewhere.
        ("दो पैनल और दो लाख", "[n] पैनल और [n]"),
        ("भेज दो, दो लाख में", "भेज दो, [n] में"),
        ("दो-तीन लाख", "[n]"),
        # Other everyday words: a number only next to a number word.
        ("saath hazaar", "[n]"),
        ("das hazaar, Mr Das", "[n], Mr Das"),
        ("tera lakh", "[n]"),
        ("दो अरब", "[n]"),
        ("आधी लाख", "[n]"),
        ("पाव किलो, पावणे दोन", "पाव किलो, [n]"),
        # Two number words written as one word.
        ("fortyfive per watt, TwentyFive, teenlakh, dolakh", "[n] per watt, [n], [n], [n]"),
        ("पाचहजार रुपये, दोलाख, एकशे वीस", "[n], [n], [n]"),
        ("tendon, Picasso, Shellac, नवलखा, हजारी", "tendon, Picasso, Shellac, नवलखा, हजारी"),
        # Possessives, short units after words, "do" before a unit.
        ("the lakh's worth, forty k", "the [n] worth, [n]"),
        ("do saal warranty, do kW", "[n] saal warranty, [n] kW"),
        # "and" before digits or a rupee word starts another number.
        ("₹45/W and 3.7 lakh; INR45 and inr 45", "[n] and [n]; [n] and [n]"),
        # A number word inside a hyphenated word is still a whole word.
        ("a half-hearted reply, three-phase supply", "a [n]-hearted reply, [n]-phase supply"),
    ],
)  # fmt: skip
def test_everyday_number_words_in_context(text: str, expected: str) -> None:
    assert _masked(text) == expected


def test_a_long_summary_masks_everything_and_keeps_the_rest() -> None:
    summary = (
        "Customer Rupesh Kulkarni from Kothrud wants a 5 kW on-grid system for a 3BHK flat; "
        "the bill is ₹4,200 a month. Salesperson quoted ₹45/W (₹2.25 lakh for 5 kW), "
        "competitor offered paune teen lakh, customer can pay saade teen lakh max. "
        "ग्राहकाचे बजेट साडेतीन लाखांपर्यंत आहे; दर ४५ प्रति वॅट जास्त वाटतो. "
        "Lakhan will visit on 20/10 at 11 am; दो दिन में कोटेशन भेजेंगे."
    )
    assert _masked(summary) == (
        "Customer Rupesh Kulkarni from Kothrud wants a [n] kW on-grid system for a [n] flat; "
        "the bill is [n] a month. Salesperson quoted [n] ([n] for [n] kW), "
        "competitor offered [n], customer can pay [n] max. "
        "ग्राहकाचे बजेट [n] आहे; दर [n] प्रति वॅट जास्त वाटतो. "
        "Lakhan will visit on [n] at [n] am; [n] दिन में कोटेशन भेजेंगे."
    )


# --- Check 4, 18 Oct (round 4, table-driven, the check's own phrases) ----------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        # B4: an everyday number word next to a rupee word or sign.
        ("saath rupay per watt", "[n] per watt"),
        ("sath rupaye prati watt", "[n] prati watt"),
        ("Rs saath per watt", "[n] per watt"),
        ("₹ saath", "[n]"),
        ("rupees saath only", "[n] only"),
        ("das rupaye per unit", "[n] per unit"),
        ("bara rupaye unit", "[n] unit"),
        ("नव रुपये", "[n]"),
        # M1: spellings missing from the lists, and the fallback for spellings we lack.
        ("pantalis rupaye per watt", "[n] per watt"),
        ("पैतालीस रुपये प्रति वॉट", "[n] प्रति वॉट"),
        ("पेंतालीस रुपये", "[n]"),
        ("सैतालीस प्रति वॅट", "[n] प्रति वॅट"),
        ("पंचावन रुपये प्रति वॅट", "[n] प्रति वॅट"),
        ("पंचेचाळिस रुपये", "[n]"),
        ("चालिस हजार", "[n]"),
        ("तैतालीस हजार", "[n]"),
        ("पच्चिस हजार", "[n]"),
        ("पासष्ठ हजार", "[n]"),
        ("adhai lakh", "[n]"),
        ("अढ़ाई लाख", "[n]"),
        ("pachpanne rupaye per watt", "[n] per watt"),
        ("चौपन्न रुपये", "[n]"),
        ("trisath hazaar ka budget", "[n] ka budget"),
        # M2: ranges with "se" and doubled "do".
        ("do se teen lakh", "[n] se [n]"),
        ("saath se sattar hazaar", "[n] se [n]"),
        ("do-do hazaar", "[n]"),
        ("das ya pandrah hazaar", "[n] ya [n]"),
        # M3: an everyday number word after a cost word.
        ("rate saath hai", "rate [n] hai"),
        ("rate sirf saath", "rate sirf [n]"),
        # Minor: the honorific stays before a name; "sau" with a number or rupees goes.
        ("Sau. Sunita Patil will decide", "Sau. Sunita Patil will decide"),
        ("सौ. सुनीता पाटील निर्णय घेतील", "सौ. सुनीता पाटील निर्णय घेतील"),
        ("paanch sau. Then the visit", "[n]. Then the visit"),
        ("सौ रुपये", "[n]"),
        ("rate sau. Ok", "rate [n]. Ok"),
        # Ordinary words before a money or rupee word stay.
        ("Spent lakhs on inverters.", "Spent [n] on inverters."),
        ("Customer asked in rupees", "Customer asked in rupees"),
        ("ग्राहक म्हणाला लाख", "ग्राहक म्हणाला [n]"),
        ("quoted Rs 45 per watt", "quoted [n] per watt"),
    ],
)  # fmt: skip
def test_check_4_phrases(text: str, expected: str) -> None:
    assert _masked(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # Check 4's must-keep names, places and homographs (all passed; they must still pass).
        "Sathe ji will confirm the roof size", "Mrs Satpute from Sinhagad Road",
        "Navale Bridge site, Narhe", "Customer lives in Pimple Nilakh",
        "Panchshil Towers, Kharadi", "Satara Road, Dhankawadi", "सातारा रोड, धनकवडी",
        "सौर ऊर्जा प्रणाली बसवायची आहे", "सातबारा उतारा पाठवायचा आहे", "एकदा साइट पाहून ठरवू",
        "आठवड्याभरात कळवतो", "चारचाकी पार्किंगवर छत आहे", "Rupesh and Ekta will visit on Monday",
        "Lakhani Builders project in Baner", "Hazarika Solar was the other quote",
        "Do you want the dongle?", "No one at home on weekdays", "Teenage son will decide",
        "Das sir from Kondhwa", "Mr Das said they will decide", "Saathi app login help",
        "Ghar ke saath office bhi", "Main bhi saath aaunga", "मैं भी साथ आऊंगा",
        "उनके साथ बात करेंगे", "कोटेशन भेज दो।", "बता दो कल तक", "Bhai, kal tak bata do",
        "Customer said do it fast", "Navratna Society, Aundh", "Dasharath Pawar from Bhosari",
        "Saswad Road site", "GST ke saath milega", "Rate was discussed, will share later",
    ],
)  # fmt: skip
def test_check_4_must_keep(text: str) -> None:
    assert mask_numbers(text) == text
