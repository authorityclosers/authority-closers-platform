"""Daily US dollar to rupee reference rates for Admin's rupee figures (orchestrator, 20 Oct
2026).

Providers bill in US dollars. Admin converted at one planning rate, ₹100 per $1, set with the
price sheet on 19 Sep 2026; that was a planning number, not an owner decision. Rupee figures
now use each day's reference rate from the European Central Bank's euro foreign exchange
reference rates (published on TARGET working days around 16:00 CET): rupees per dollar is
that day's INR rate divided by its USD rate. A day without a rate (a weekend or holiday)
uses the latest earlier one, and each figure names the rate and its date. The planning rate
stays available as an option.

The feed is a small fixed XML document; it is read with two patterns, never an XML parser,
so no entity or external reference in it can do anything.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

ECB_90_DAYS = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
SOURCE = "ECB"
# A rate outside this band is a broken feed, never a real rupee.
PLAUSIBLE = (Decimal(40), Decimal(250))
_DAY = re.compile(r"<Cube\s+time=['\"](\d{4}-\d{2}-\d{2})['\"]\s*>(.*?)</Cube>", re.DOTALL)
_RATE = re.compile(
    r"<Cube\s+currency=['\"]([A-Z]{3})['\"]\s+rate=['\"]([0-9]{1,6}(?:\.[0-9]{1,8})?)['\"]\s*/>"
)


def parse_ecb(document: str) -> dict[date, Decimal]:
    """Rupees per US dollar for each day the feed lists both currencies."""
    rates: dict[date, Decimal] = {}
    for day_text, body in _DAY.findall(document[:2_000_000]):
        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            continue
        quotes = dict(_RATE.findall(body))
        try:
            usd, inr = Decimal(quotes["USD"]), Decimal(quotes["INR"])
        except (KeyError, InvalidOperation):
            continue
        if usd <= 0:
            continue
        rate = (inr / usd).quantize(Decimal("0.0001"))
        if PLAUSIBLE[0] <= rate <= PLAUSIBLE[1]:
            rates[day] = rate
    return rates


def rate_on(rates: Mapping[date, Decimal], day: date) -> tuple[date, Decimal] | None:
    """The rate for a day: that day's, else the latest earlier one; None before the first."""
    earlier = [known for known in rates if known <= day]
    if not earlier:
        return None
    chosen = max(earlier)
    return chosen, rates[chosen]
