"""P2 API and receipt concurrency on the isolated, migrated product-updates store."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.http.product_updates import install_product_updates_http
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.product_updates.models import Notification, ProductUpdate, UpdateSeen
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


async def test_read_all_is_atomic_idempotent_and_covers_older_account_events(
    updates_engine: Engine,
) -> None:
    engine = create_async_engine(updates_engine.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor = ActorContext(uuid4(), uuid4(), None)
    neighbor = ActorContext(uuid4(), uuid4(), None)
    now = datetime.now(UTC)
    prior_read_at = now - timedelta(days=1)
    try:
        async with sessions() as database, database.begin():
            database.add_all(
                Person(
                    id=recipient.person_id, email=f"fictional-{recipient.person_id}@example.test"
                )
                for recipient in (actor, neighbor)
            )
            await database.flush()
            database.add_all(
                Notification(
                    person_id=recipient.person_id,
                    kind="report_ready",
                    dedupe_key=f"fictional-report-{index}",
                    title="Fictional report",
                    body="Ready to read.",
                    href="/analysis/calls/fictional",
                    created_at=now - timedelta(hours=index),
                    read_at=prior_read_at if index == 0 else None,
                )
                for recipient in (actor, neighbor)
                for index in range(55)
            )

        with pytest.raises(RuntimeError, match="fictional rollback"):
            async with sessions() as database, database.begin():
                service = ProductUpdatesReading(database, actor, environment="staging")
                before = await service.notifications()
                assert len(before["notifications"]) == 50 and before["unread_count"] == 55
                assert await service.mark_all_read() == {"unread_count": 0}
                raise RuntimeError("fictional rollback")

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
            assert (await client.get("/v1/notifications")).json()["unread_count"] == 55
            for _ in range(2):
                response = await client.post(
                    "/v1/notifications/read-all", json={}, headers={"Origin": origin}
                )
                assert response.status_code == 200 and response.json() == {"unread_count": 0}
                assert response.headers["cache-control"] == "private, no-store"

        async with sessions() as database, database.begin():
            other_device = ActorContext(actor.person_id, uuid4(), None)
            assert (
                await ProductUpdatesReading(database, other_device, environment="staging").updates()
            )["unseen_count"] == 0
            assert (
                await ProductUpdatesReading(
                    database, neighbor, environment="staging"
                ).notifications()
            )["unread_count"] == 55
            rows = (
                await database.scalars(
                    select(Notification).where(
                        Notification.person_id.in_([actor.person_id, neighbor.person_id])
                    )
                )
            ).all()
            for row in rows:
                if row.dedupe_key == "fictional-report-0":
                    assert row.read_at == prior_read_at
                elif row.person_id == actor.person_id:
                    assert row.read_at is not None
                elif row.person_id == neighbor.person_id:
                    assert row.read_at is None
            receipts = (
                await database.scalars(
                    select(UpdateSeen).where(UpdateSeen.person_id == actor.person_id)
                )
            ).all()
            assert len(receipts) == 6
    finally:
        await engine.dispose()
