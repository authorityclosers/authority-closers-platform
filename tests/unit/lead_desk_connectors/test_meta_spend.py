"""Ad spend per Meta campaign: reading Meta's insights, and what each lead cost."""

import asyncio
import json
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs

import httpx

from ac_platform.lead_desk.connectors import meta, meta_spend
from tests.unit.lead_desk_connectors.test_meta import cfg as meta_cfg


def test_meta_lead_count_prefers_the_lead_action() -> None:
    assert meta_spend.leads_from([{"action_type": "lead", "value": "7"}]) == 7
    assert (
        meta_spend.leads_from(
            [
                {"action_type": "link_click", "value": "90"},
                {"action_type": "onsite_conversion.lead_grouped", "value": "5"},
            ]
        )
        == 5
    )
    assert meta_spend.leads_from(None) == 0
    assert meta_spend.leads_from([{"action_type": "lead", "value": "x"}]) == 0


def test_a_row_becomes_one_campaign_day() -> None:
    row = meta_spend.parse_row(
        "act_101",
        {
            "campaign_id": "120000000000001",
            "campaign_name": "Fictional Homes · 3 BHK",
            "spend": "1234.567",
            "impressions": "10000",
            "clicks": "321",
            "actions": [{"action_type": "lead", "value": "12"}],
            "account_currency": "inr",
            "date_start": "2026-10-18",
        },
        "",
    )
    assert row == meta_spend.SpendRow(
        "act_101",
        "120000000000001",
        "Fictional Homes · 3 BHK",
        date(2026, 10, 18),
        "INR",
        Decimal("1234.57"),
        10000,
        321,
        12,
    )
    assert (
        meta_spend.parse_row("act_101", {"campaign_id": "x", "date_start": "2026-10-18"}, "")
        is None
    )
    assert meta_spend.parse_row("act_101", {"campaign_id": "1", "date_start": "bad"}, "") is None


def test_insights_are_read_per_day_and_page_by_page() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = {key: values[0] for key, values in parse_qs(request.url.query.decode()).items()}
        seen.append(query)
        assert request.url.path == "/v23.0/act_101/insights"
        day = "2026-10-17" if "after" not in query else "2026-10-18"
        body: dict[str, Any] = {
            "data": [
                {
                    "campaign_id": "120000000000001",
                    "campaign_name": "Enquiries",
                    "spend": "100.00",
                    "account_currency": "INR",
                    "date_start": day,
                }
            ]
        }
        if "after" not in query:
            body["paging"] = {"next": "x", "cursors": {"after": "A"}}
        return httpx.Response(200, json=body)

    graph = meta.Graph(meta_cfg(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    rows = asyncio.run(
        meta_spend.insights(
            graph, "token", "act_101", since=date(2026, 10, 17), until=date(2026, 10, 18)
        )
    )
    assert [row.day for row in rows] == [date(2026, 10, 17), date(2026, 10, 18)]
    first = seen[0]
    assert first["level"] == "campaign" and first["time_increment"] == "1"
    assert json.loads(first["time_range"]) == {"since": "2026-10-17", "until": "2026-10-18"}
    assert "spend" in first["fields"] and "actions" in first["fields"]


def test_cost_per_lead_and_totals_per_currency() -> None:
    def campaign(currency: str, spend: str, leads: int, won: int) -> meta_spend.CampaignSpend:
        return meta_spend.CampaignSpend(
            "act_1", "1", "C", currency, Decimal(spend), 0, 0, leads, leads, won
        )

    one = campaign("INR", "1000.00", 4, 1)
    assert (one.per_lead, one.per_customer) == (Decimal("250.00"), Decimal("1000.00"))
    assert campaign("INR", "10.00", 0, 0).per_lead is None
    totals = meta_spend.totals(
        [one, campaign("INR", "500.00", 6, 0), campaign("USD", "9.99", 3, 0)]
    )
    assert totals["INR"] == {
        "spend": Decimal("1500.00"),
        "leads": 10,
        "won": 1,
        "per_lead": Decimal("150.00"),
    }
    assert totals["USD"]["per_lead"] == Decimal("3.33")
