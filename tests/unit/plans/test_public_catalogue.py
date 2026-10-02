"""Unit proof for the public plans catalogue (Plans C2): redaction, strict shape, route."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from ac_platform.http.plans import install_plans_http
from ac_platform.http.rate_limits import DEFAULT_RATE_LIMIT_RULES
from ac_platform.plans import Plan
from ac_platform.plans.catalogue import (
    PublicPlan,
    PublicPlanCatalogue,
    PublicTopUpPack,
    public_plan,
)

PACKS = [
    {
        "key": "pack_small",
        "minutes": 60,
        "validity_rule": "billing_year_end",
        "price_paise": 49_900,
        "price_cents": 599,
    }
]
PUBLIC_KEYS = {
    "key",
    "name",
    "audience",
    "status",
    "prices",
    "included_minutes",
    "seat_min",
    "seat_max",
    "per_seat",
    "longest_call_minutes",
    "retention_days",
    "rollover_months",
    "feature_keys",
    "top_up_packs",
    "sort_order",
    "revision",
}


def _plan(status: str, **overrides: Any) -> Plan:
    fields: dict[str, Any] = {
        "key": "personal",
        "name": "Personal",
        "audience": "For one salesperson",
        "status": status,
        "monthly_price_paise": 99_900,
        "yearly_price_paise": 999_900,
        "monthly_price_cents": 1_299,
        "yearly_price_cents": 12_999,
        "included_minutes": 300,
        "seat_min": 1,
        "seat_max": 1,
        "per_seat": True,
        "longest_call_minutes": 90,
        "retention_days": 365,
        "rollover_months": 1,
        "feature_keys": ["sales_xray_reports"],
        "top_up_packs": PACKS,
        "sort_order": 10,
        "revision": 3,
    }
    fields.update(overrides)
    return Plan(**fields)


def _json(plan: PublicPlan) -> dict[str, Any]:
    return PublicPlanCatalogue(plans=[plan]).model_dump(mode="json")["plans"][0]


def test_coming_soon_redacts_stored_prices_and_strips_pack_price_keys() -> None:
    body = _json(public_plan(_plan("coming_soon")))
    assert set(body) == PUBLIC_KEYS
    assert body["prices"] is None
    assert body["top_up_packs"] == [
        {"key": "pack_small", "minutes": 60, "validity_rule": "billing_year_end"}
    ]
    assert body["per_seat"] is True
    assert body["revision"] == 3
    assert body["included_minutes"] == 300


def test_active_publishes_named_prices_and_pack_prices() -> None:
    body = _json(public_plan(_plan("active")))
    assert set(body) == PUBLIC_KEYS
    assert body["prices"] == {
        "monthly_paise": 99_900,
        "yearly_paise": 999_900,
        "monthly_cents": 1_299,
        "yearly_cents": 12_999,
    }
    assert body["top_up_packs"] == PACKS


def test_active_with_unset_prices_stays_null_inside_prices() -> None:
    body = _json(
        public_plan(
            _plan(
                "active",
                monthly_price_paise=None,
                yearly_price_paise=None,
                monthly_price_cents=None,
                yearly_price_cents=None,
            )
        )
    )
    assert body["prices"] == dict.fromkeys(
        ("monthly_paise", "yearly_paise", "monthly_cents", "yearly_cents")
    )


@pytest.mark.parametrize("status", ["draft", "retired"])
def test_private_statuses_are_refused(status: str) -> None:
    with pytest.raises(ValueError, match="not public"):
        public_plan(_plan(status))


def test_strict_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        PublicTopUpPack.model_validate(
            {"key": "pack", "minutes": 1, "validity_rule": "billing_year_end", "price_paise": 1}
        )
    body = _json(public_plan(_plan("active")))
    with pytest.raises(ValidationError):
        PublicPlan.model_validate({**body, "id": "private"})


class _Database:
    def __init__(self, rows: list[Plan]) -> None:
        self.rows = rows
        self.statements: list[str] = []

    async def __aenter__(self) -> _Database:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def begin(self) -> _Database:
        return self

    async def scalars(self, statement: Any) -> list[Plan]:
        self.statements.append(str(statement))
        return self.rows


def _get(rows: list[Plan]) -> tuple[httpx.Response, _Database]:
    database = _Database(rows)
    application = FastAPI()
    install_plans_http(application, sessions=lambda: database)  # type: ignore[arg-type]

    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/v1/plans")

    return asyncio.run(call()), database


def test_route_is_unauthenticated_cached_and_filters_and_orders_in_sql() -> None:
    response, database = _get(
        [_plan("coming_soon"), _plan("active", key="organisation", sort_order=20)]
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    plans = response.json()["plans"]
    assert [plan["key"] for plan in plans] == ["personal", "organisation"]
    assert plans[0]["prices"] is None and plans[1]["prices"] is not None
    assert "price_paise" not in plans[0]["top_up_packs"][0]
    assert plans[1]["top_up_packs"] == PACKS
    (statement,) = database.statements
    assert "plans.status IN" in statement
    assert "ORDER BY plans.sort_order, plans.key" in statement


def test_route_returns_an_empty_list() -> None:
    response, _ = _get([])
    assert response.status_code == 200
    assert response.json() == {"plans": []}


def test_public_rate_limit_rule_covers_only_the_catalogue_read() -> None:
    (rule,) = [rule for rule in DEFAULT_RATE_LIMIT_RULES if rule.name == "public-plans-catalogue"]
    assert (rule.method, rule.capacity, rule.refill_seconds) == ("GET", 300, 60)
    assert rule.path.fullmatch("/v1/plans")
    assert not rule.path.fullmatch("/v1/plans/personal")
