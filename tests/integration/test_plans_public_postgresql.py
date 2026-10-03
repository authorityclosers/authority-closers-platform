"""Real PostgreSQL proof for the public plans catalogue (Plans C2, fictional rows only).

The migrated seeds answer as three coming-soon rows with NULL prices; an empty public
set answers an empty list; ``draft`` and ``retired`` rows never appear; stored prices
on a coming-soon row and its packs stay hidden; ordering is ``sort_order`` then
``key``; the revision travels; no actor or cookie is needed.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.http.plans import install_plans_http
from ac_platform.plans import Plan
from tests.integration.test_media_delivery_renewal_postgresql import _run_async
from tests.integration.test_media_delivery_renewal_postgresql import (
    postgres_harness as postgres_harness,  # noqa: F401 - disposable migrated schema fixture
)

SEED_KEYS = ["personal", "organisation", "enterprise"]
PRICED_PACK = {
    "key": "pack_fictional",
    "minutes": 120,
    "validity_rule": "billing_year_end",
    "price_paise": 77_700,
    "price_cents": 999,
}
PRICES = {
    "monthly_price_paise": 11_100,
    "yearly_price_paise": 111_100,
    "monthly_price_cents": 222,
    "yearly_price_cents": 2_222,
}


def _row(key: str, status: str, sort_order: int, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid4(),
        "key": key,
        "name": f"Fictional {key}",
        "audience": "Fictional audience",
        "status": status,
        "per_seat": False,
        "feature_keys": [],
        "top_up_packs": [],
        "sort_order": sort_order,
        "revision": 1,
        **PRICES,
    }
    row.update(overrides)
    return row


def test_public_catalogue_reads_redacts_and_orders(postgres_harness: Any) -> None:  # noqa: F811
    async def run() -> None:
        engine = create_async_engine(postgres_harness.schema_url, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        application = FastAPI()
        install_plans_http(application, sessions=sessions)
        transport = httpx.ASGITransport(app=application)
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                # Migrated seeds: the dev check, read with no cookie or header.
                response = await client.get("/v1/plans")
                assert response.status_code == 200, response.text
                assert response.headers["cache-control"] == "public, max-age=60"
                plans = response.json()["plans"]
                assert [plan["key"] for plan in plans] == SEED_KEYS
                assert {plan["status"] for plan in plans} == {"coming_soon"}
                assert all(plan["prices"] is None for plan in plans)
                assert all(plan["per_seat"] is False for plan in plans)
                assert all("id" not in plan and "created_at" not in plan for plan in plans)

                async with sessions() as database, database.begin():
                    await database.execute(update(Plan).values(status="draft"))
                empty = await client.get("/v1/plans")
                assert empty.status_code == 200
                assert empty.json() == {"plans": []}

                async with sessions() as database, database.begin():
                    await database.execute(
                        insert(Plan),
                        [
                            _row("zeta_soon", "coming_soon", 5, top_up_packs=[PRICED_PACK]),
                            _row("alpha_soon", "coming_soon", 5, revision=4, per_seat=True),
                            _row(
                                "beta_live",
                                "active",
                                1,
                                top_up_packs=[PRICED_PACK],
                                included_minutes=600,
                            ),
                            _row("gamma_retired", "retired", 0),
                            _row("delta_draft", "draft", 0),
                        ],
                    )
                body = (await client.get("/v1/plans")).json()
        finally:
            await engine.dispose()

        plans = {plan["key"]: plan for plan in body["plans"]}
        assert [plan["key"] for plan in body["plans"]] == ["beta_live", "alpha_soon", "zeta_soon"]
        assert plans["beta_live"]["prices"] == {
            "monthly_paise": 11_100,
            "yearly_paise": 111_100,
            "monthly_cents": 222,
            "yearly_cents": 2_222,
        }
        assert plans["beta_live"]["top_up_packs"] == [PRICED_PACK]
        assert plans["beta_live"]["included_minutes"] == 600
        assert plans["zeta_soon"]["prices"] is None
        assert plans["zeta_soon"]["top_up_packs"] == [
            {"key": "pack_fictional", "minutes": 120, "validity_rule": "billing_year_end"}
        ]
        assert plans["alpha_soon"]["revision"] == 4
        assert plans["alpha_soon"]["per_seat"] is True
        for key in ("zeta_soon", "alpha_soon"):
            assert not {"77700", "999", "11100", "2222"} & set(
                str(plans[key]).replace(",", " ").replace("}", " ").split()
            )

    _run_async(run())
