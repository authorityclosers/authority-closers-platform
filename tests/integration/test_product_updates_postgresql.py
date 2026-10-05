"""0074→head upgrade preserves capability history and seeds the frozen changelog."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from ac_platform.authorization.models import CapabilityGrant, CapabilityRevocation
from ac_platform.db.models import model_metadata
from ac_platform.product_updates.models import ProductUpdate
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
        head = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()
        with Session(engine) as database:
            assert database.scalar(text("SELECT version_num FROM alembic_version")) == head
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
