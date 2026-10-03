"""Fictional ETH-03 phrases only; no research corpus content."""

import pytest

from ac_platform.conversation_intelligence.sensitive_terms import PROFILE, detect_sensitive_terms


@pytest.mark.parametrize("rule", PROFILE["rules"], ids=lambda rule: rule["rule_id"])
def test_each_rule_in_hinglish_and_devanagari(rule):
    for pattern in rule["patterns"]:
        hits = detect_sensitive_terms([("fictional-1", f"Demo widget: {pattern}, do lakh.")])
        assert ("fictional-1", rule["category"], rule["rule_id"]) in hits
        assert len(hits) == len(set(hits))
        assert all(not any(c.isdigit() for c in p) for p in rule["patterns"])


@pytest.mark.parametrize(
    "text",
    [
        "Demo turnover do crore, margin bees percent, target pachaas lakh.",
        "काल्पनिक टर्नओवर दो करोड़, मार्जिन बीस प्रतिशत, लक्ष्य पचास लाख।",
        "Fictional credit terms tees din, payment hazaar, turnover 20000000.",
        "काल्पनिक क्रेडिट तीस दिन, भुगतान एक हजार, लक्ष्य दो लाख।",
        "123 १२३ lakh crore hazaar लाख करोड़ हजार cash flow tax invoice bookshelves",
        "Fictional kaccha aam; cash mein payment; कच्चा आम; कैश में भुगतान।",
    ],
)
def test_ordinary_figures_and_word_magnitudes_never_fire(text):
    assert detect_sensitive_terms([("fictional-negative", text)]) == ()


def test_normalization_boundaries_and_one_hit_per_rule():
    assert detect_sensitive_terms([("s1", "ＣＡＳＨ ONLY cash only")]) == (
        ("s1", "SENSITIVE_FINANCIAL", "cash_only"),
    )
    assert detect_sensitive_terms([("s1", "cash onlyish")]) == ()
    assert detect_sensitive_terms([]) == ()
