"""0074→0075 upgrade preserves capability history and seeds the frozen changelog."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi import FastAPI
from sqlalchemy import Engine, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.authorization.models import CapabilityGrant, CapabilityRevocation
from ac_platform.db.models import model_metadata
from ac_platform.http.product_updates import install_product_updates_http
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.product_updates.models import ProductUpdate, UpdateSeen
from ac_platform.product_updates.reading import ProductUpdatesReading
from tests.database.test_capability_grants import audit, grant, seed_scope
from tests.database.test_capability_grants_postgresql import _postgres_schema

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def updates_engine() -> Iterator[Engine]:
    with _postgres_schema(current_application=False) as engine:
        environment = os.environ | {
            "AC_DATABASE_URL": engine.url.set(query={}).render_as_string(hide_password=False),
            "AC_DATABASE_MIGRATOR_URL": engine.url.set(query={}).render_as_string(
                hide_password=False
            ),
            "AC_ENVIRONMENT": "test",
            "PGOPTIONS": engine.url.query["options"],
            "PYTHONPATH": str(ROOT / "packages/python"),
        }

        def migrate(target: str) -> None:
            result = subprocess.run(  # noqa: S603 - fixed local migration command
                [sys.executable, "-m", "alembic", "upgrade", target],
                env=environment,
                cwd=ROOT,
                capture_output=True,
                timeout=180,
                check=False,
            )
            if result.returncode != 0:
                pytest.fail(f"isolated product update upgrade to {target} failed")

        migrate("20261004_0074")
        with Session(engine) as database:
            scope = seed_scope(database)
            row = grant(database, scope)
            database.add(row)
            database.flush()
            revocation = CapabilityRevocation(
                grant_id=row.id,
                revoked_by_person_id=scope.actor,
                audit_event_id=audit(database, scope),
                reason="Fictional previous revocation",
            )
            database.add(revocation)
            database.commit()
            grant_id, revocation_id = row.id, revocation.id
        migrate("head")
        with Session(engine) as database:
            assert (
                database.scalar(text("SELECT version_num FROM alembic_version")) == "20261004_0075"
            )
            assert database.get(CapabilityGrant, grant_id).permission == "catalog_read"
            assert database.get(CapabilityRevocation, revocation_id).grant_id == grant_id
        yield engine


def test_six_seed_notes_match_the_original_text_and_order(updates_engine: Engine) -> None:
    source = (ROOT / "apps/sales-xray-web/app/shell/changelog.ts").read_text()
    entries = re.findall(
        r'\{\s*id: "([^"]+)",\s*date: "([^"]+)",\s*title: "([^"]+)",\s*items: (\[.*?\])',
        source,
        re.DOTALL,
    )
    assert len(entries) == 6
    with Session(updates_engine) as database:
        rows = database.scalars(
            select(ProductUpdate)
            .where(ProductUpdate.created_by == "seed")
            .order_by(ProductUpdate.published_at.desc())
        ).all()
        assert len(rows) == 6
        for row, (slug, day, title, items) in zip(rows, entries, strict=True):
            assert (row.note_key, row.note_date.isoformat(), row.title, row.items) == (
                "seed-" + slug,
                day,
                title,
                json.loads(re.sub(r",\s*\]", "]", items)),
            )
            assert (row.version, row.status, row.release_id, row.audience, row.major) == (
                1,
                "published",
                "changelog-2026-09-30",
                "everyone",
                False,
            )
            assert (
                row.supersedes_id
                is row.source_pr
                is row.feature_key
                is row.created_by_person_id
                is None
            )
            assert row.created_at is not None and row.published_at is not None


def test_migrated_schema_matches_models(updates_engine: Engine) -> None:
    with updates_engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


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
