"""Ask Dipak's saved lessons and Next-call missions on PostgreSQL (Dipak's spec, 13 Nov 2026;
migration 0153).

A signed-in person saves and unsaves lessons and marks and undoes missions from a Sales X-Ray
address; each change is one appended row, a repeat adds none, and what they see is folded from
their own rows only. Only Dipak's 150 questions are accepted, a mission only where the question
has a lesson, and writes only from the app's own pages. Missions marked done stay countable per
lesson. The table is append-only and the migration rolls back only while it is empty.
Disposable loopback PostgreSQL, fictional people.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.ask_dipak import http as ask_http
from ac_platform.ask_dipak import store
from ac_platform.ask_dipak.models import SalesXrayAskDipakEvent
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

ROOT = Path(__file__).resolve().parents[2]
FILE = "20261114_0153_sales_xray_ask_dipak.py"
WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
PROGRESS = "/v1/sales-xray/ask-dipak/progress"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("sales_xray_ask_dipak_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_schema_gate_and_forward_recovery_with_history() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert module.revision == "20261114_0153"
    assert module.down_revision.endswith("_0152")
    assert any((ROOT / "db/migrations/versions").glob(f"{module.down_revision}_*.py"))
    path = Path(module.__file__)
    check_operations([classify_source(path.read_text(), str(path))], set())
    module.op = SimpleNamespace(
        execute=lambda statement: None,
        get_bind=lambda: SimpleNamespace(scalar=lambda statement: True),
    )
    with pytest.raises(RuntimeError, match="history requires forward recovery"):
        module.downgrade()


def _install(setup: Any) -> None:
    ask_http.install_ask_dipak_http(
        setup.app, RouteContext(setup.settings, setup.require_actor, setup.sessions)
    )


async def _rows(setup: Any) -> int:
    async with setup.sessions() as db:
        return int(await db.scalar(select(func.count()).select_from(SalesXrayAskDipakEvent)) or 0)


def test_a_person_saves_lessons_and_marks_missions_kept_on_their_account(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        me = setup.state.person_id
        try:
            _install(setup)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)

                first = await http.get(PROGRESS)
                assert first.status_code == 200, first.text
                assert first.json() == {"saved": [], "missions": [], "missions_done": 0}
                assert first.headers["cache-control"] == "private, no-store"

                # Writes come only from the app's own pages.
                bare = await http.put(f"{PROGRESS}/PB03", json={"item": "saved", "on": True})
                assert bare.status_code == 403
                assert await _rows(setup) == 0

                # Save twice, mark the mission, and the rows say each change once.
                for _ in range(2):
                    saved = await http.put(
                        f"{PROGRESS}/PB03", json={"item": "saved", "on": True}, headers=WRITE
                    )
                    assert saved.status_code == 200, saved.text
                    assert saved.json()["saved"] == ["PB03"]
                assert await _rows(setup) == 1
                done = await http.put(
                    f"{PROGRESS}/NEW-035", json={"item": "mission", "on": True}, headers=WRITE
                )
                assert done.json() == {
                    "saved": ["PB03"],
                    "missions": ["NEW-035"],
                    "missions_done": 1,
                }
                again = await http.get(PROGRESS)
                assert again.json() == done.json()

                # Undo both; the history keeps every step.
                for path, item in (("PB03", "saved"), ("NEW-035", "mission")):
                    off = await http.put(
                        f"{PROGRESS}/{path}", json={"item": item, "on": False}, headers=WRITE
                    )
                    assert off.status_code == 200, off.text
                assert (await http.get(PROGRESS)).json()["missions_done"] == 0
                assert await _rows(setup) == 4
                redo = await http.put(
                    f"{PROGRESS}/NEW-035", json={"item": "mission", "on": True}, headers=WRITE
                )
                assert redo.json()["missions"] == ["NEW-035"]

                # Only Dipak's questions; a mission only where there is a lesson.
                unknown = await http.put(
                    f"{PROGRESS}/ZZ99", json={"item": "saved", "on": True}, headers=WRITE
                )
                assert unknown.status_code == 404
                malformed = await http.put(
                    f"{PROGRESS}/pb03", json={"item": "saved", "on": True}, headers=WRITE
                )
                assert malformed.status_code == 422
                no_lesson = await http.put(
                    f"{PROGRESS}/PB05", json={"item": "mission", "on": True}, headers=WRITE
                )
                assert no_lesson.status_code == 422
                assert "no Next-call mission" in no_lesson.json()["detail"]
                bad_item = await http.put(
                    f"{PROGRESS}/PB03", json={"item": "score", "on": True}, headers=WRITE
                )
                assert bad_item.status_code == 422
                # A lesson without one is still saved, as a bookmark.
                bookmark = await http.put(
                    f"{PROGRESS}/PB05", json={"item": "saved", "on": True}, headers=WRITE
                )
                assert bookmark.json()["saved"] == ["PB05"]

            # Someone else's progress is their own.
            other = uuid4()
            async with setup.sessions() as db, db.begin():
                db.add(
                    Person(
                        id=other,
                        email=f"other-{other.hex[:8]}@example.test",
                        display_name="Other Seller",
                        email_verified_at=datetime.now(UTC),
                    )
                )
            async with setup.sessions() as db, db.begin():
                theirs = await store.set_item(
                    db,
                    person_id=other,
                    tenant_id=None,
                    question_id="OB03",
                    item="saved",
                    on=True,
                    now=datetime.now(UTC),
                )
            assert theirs.saved == ("OB03",)
            async with setup.sessions() as db:
                mine = await store.progress_for(db, me)
                assert "OB03" not in mine.saved
                assert mine.saved == ("PB05",)
                # Missions marked done stay countable per lesson, for Growth.
                assert (await store.missions_marked(db, me)) == {"NEW-035": 2}
                rows = (
                    await db.scalars(
                        select(SalesXrayAskDipakEvent).where(SalesXrayAskDipakEvent.person_id == me)
                    )
                ).all()
                assert {row.tenant_id for row in rows} == {setup.state.tenant_id}
            # A deleted account takes its progress with it, and only its own.
            async with setup.sessions() as db, db.begin():
                assert await store.erase_ask_dipak_for_person(db, person_id=other) == 1
            async with setup.sessions() as db:
                assert (await store.progress_for(db, other)).saved == ()
                assert (await store.progress_for(db, me)).saved == ("PB05",)
        finally:
            await setup.engine.dispose()

    run(exercise())
