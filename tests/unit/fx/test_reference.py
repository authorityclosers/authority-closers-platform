"""Daily rupee reference rates from the ECB feed: read safely, looked up by day."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ac_platform.fx.reference import parse_ecb, rate_on

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
  xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube>
    <Cube time="2026-10-20">
      <Cube currency="USD" rate="1.0800"/>
      <Cube currency="JPY" rate="162.10"/>
      <Cube currency="INR" rate="95.3640"/>
    </Cube>
    <Cube time='2026-10-16'>
      <Cube currency='USD' rate='1.0750'/>
      <Cube currency='INR' rate='94.6000'/>
    </Cube>
    <Cube time="2026-10-15">
      <Cube currency="USD" rate="1.0700"/>
    </Cube>
    <Cube time="2026-10-14">
      <Cube currency="USD" rate="1.0"/>
      <Cube currency="INR" rate="9000"/>
    </Cube>
    <Cube time="2026-13-40">
      <Cube currency="USD" rate="1.0"/>
      <Cube currency="INR" rate="90"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


def test_the_feed_gives_rupees_per_dollar_for_each_complete_day() -> None:
    rates = parse_ecb(FEED)
    # INR per euro divided by USD per euro; days missing INR, implausible or invalid skipped.
    assert rates == {
        date(2026, 10, 20): Decimal("88.3000"),
        date(2026, 10, 16): Decimal("88.0000"),
    }


def test_a_day_without_a_rate_uses_the_latest_earlier_one() -> None:
    rates = parse_ecb(FEED)
    assert rate_on(rates, date(2026, 10, 18)) == (date(2026, 10, 16), Decimal("88.0000"))
    assert rate_on(rates, date(2026, 10, 20)) == (date(2026, 10, 20), Decimal("88.3000"))
    assert rate_on(rates, date(2026, 10, 1)) is None


def test_nothing_but_the_two_patterns_is_read() -> None:
    hostile = '<!DOCTYPE x [<!ENTITY a "aaaa">]><Cube time="2026-10-20">&a;</Cube>'
    assert parse_ecb(hostile) == {}
    assert parse_ecb("") == {}
