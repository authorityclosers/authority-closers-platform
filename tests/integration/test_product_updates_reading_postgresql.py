"""P2 API and receipt concurrency on the isolated, migrated product-updates store."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.http.product_updates import install_product_updates_http
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.product_updates.models import ProductUpdate, UpdateSeen
from ac_platform.product_updates.reading import ProductUpdatesReading
from tests.integration.test_product_updates_postgresql import (
    updates_engine as updates_engine,  # noqa: F401
)


async def test_new_account_reads_six_seed_notes_and_concurrent_seen_is_safe(
    updates_engine: Engine,
) -> None:
    engine = create_async_engine(updates_engine.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    person_id, neighbor_id = uuid4(), uuid4()
    try:
        async with sessions() as database, database.begin():
            database.add_all(
                [
                    Person(id=person_id, email=f"fictional-{person_id.hex}@example.test"),
                    Person(id=neighbor_id, email=f"fictional-{neighbor_id.hex}@example.test"),
                ]
            )
        actor = ActorContext(person_id, uuid4(), None)
        async with sessions() as database, database.begin():
            result = await ProductUpdatesReading(database, actor, environment="staging").updates()
            assert result["unseen_count"] == 6
            expected = database.scalars(
                select(ProductUpdate.note_key).order_by(ProductUpdate.published_at.desc())
            )
            assert [item["key"] for item in result["updates"]] == (await expected).all()
            key = result["updates"][0]["key"]

        async def acknowledge() -> dict[str, int]:
            async with sessions() as database, database.begin():
                return await ProductUpdatesReading(
                    database, actor, environment="staging"
                ).mark_seen([key])

        assert await asyncio.wait_for(asyncio.gather(acknowledge(), acknowledge()), timeout=15) == [
            {"unseen_count": 5},
            {"unseen_count": 5},
        ]
        async with sessions() as database, database.begin():
            other_device = ActorContext(person_id, uuid4(), None)
            assert (
                await ProductUpdatesReading(database, other_device, environment="staging").updates()
            )["unseen_count"] == 5
            neighbor = ActorContext(neighbor_id, uuid4(), None)
            assert (
                await ProductUpdatesReading(database, neighbor, environment="staging").updates()
            )["unseen_count"] == 6
            receipts = (
                await database.scalars(select(UpdateSeen).where(UpdateSeen.person_id == person_id))
            ).all()
            assert len(receipts) == 1 and receipts[0].note_key == key
    finally:
        await engine.dispose()


async def test_http_seed_response_and_release_acknowledgement(updates_engine: Engine) -> None:
    engine = create_async_engine(updates_engine.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor = ActorContext(uuid4(), uuid4(), None)
    try:
        async with sessions() as database, database.begin():
            database.add(
                Person(id=actor.person_id, email=f"fictional-{actor.person_id.hex}@example.test")
            )

        async def require_actor():
            async with sessions() as database, database.begin():
                yield SimpleNamespace(database=database, resolved=SimpleNamespace(actor=actor))

        origin = "https://sales.authorityclosers.test"
        app = FastAPI()
        install_product_updates_http(
            app,
            settings=Settings(_env_file=None, environment="test", sales_xray_app_url=origin),
            require_actor=require_actor,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=origin
        ) as client:
            response = await client.get("/v1/updates")
            assert response.status_code == 200
            assert response.headers["cache-control"] == "private, no-store"
            result = response.json()
            assert result["unseen_count"] == 6 and len(result["updates"]) == 6
            assert set(result["updates"][0]) == {
                "key",
                "version",
                "release_id",
                "date",
                "title",
                "items",
                "major",
                "draft",
                "seen",
                "published_at",
            }
            assert [item["date"] for item in result["updates"]] == sorted(
                (item["date"] for item in result["updates"]),
                reverse=True,
            )
            release = (await client.get("/v1/notifications")).json()
            assert release["unread_count"] == 1
            assert release["notifications"][0]["count"] == 6
            response = await client.post(
                "/v1/notifications/read",
                json={"ids": [release["notifications"][0]["id"]]},
                headers={"Origin": origin},
            )
            assert response.status_code == 200 and response.json() == {"unread_count": 0}
            assert (await client.get("/v1/updates")).json()["unseen_count"] == 0
    finally:
        await engine.dispose()
