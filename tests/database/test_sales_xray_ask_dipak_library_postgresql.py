"""Ask Dipak's lessons from the database on PostgreSQL (owner, 16 Nov 2026: Dipak's edits as "a
database update kind of situation"; migration 0157).

Until the first import the bundled library is served. An import of his docs is checked (one
whole lesson for each of his 150 questions), shown as a dry run, then appended as one row with
an audit event naming the approver and the issue; the same import again adds nothing. The app's
lesson route then teaches the newest row, with its version, and never the lock. Disposable
loopback PostgreSQL; the lessons are Dipak's text, the people fictional.
"""

from __future__ import annotations

import copy
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.ask_dipak import catalogue, library
from ac_platform.ask_dipak.coaching_http import install_ask_dipak_coaching_http
from ac_platform.ask_dipak.models import SalesXrayAskDipakLibraryVersion
from ac_platform.audit.models import AuditEvent
from ac_platform.http.routes import RouteContext
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

ROOT = Path(__file__).resolve().parents[2]
FILE = "20261116_0157_sales_xray_ask_dipak_library.py"
SCRIPT = ROOT / "scripts/data-changes/ask-dipak-import-lessons.py"
BASE = "/v1/sales-xray/ask-dipak"
NOW = datetime(2026, 11, 16, 18, 0, tzinfo=UTC)


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_schema_gate_and_forward_recovery_with_history() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = _load(ROOT / "db/migrations/versions" / FILE, "sales_xray_ask_dipak_library")
    assert (module.revision, module.down_revision) == ("20261116_0157", "20261115_0156")
    path = Path(module.__file__)
    check_operations([classify_source(path.read_text(), str(path))], set())
    module.op = SimpleNamespace(
        execute=lambda statement: None,
        get_bind=lambda: SimpleNamespace(scalar=lambda statement: True),
    )
    with pytest.raises(RuntimeError, match="history requires forward recovery"):
        module.downgrade()


def test_an_import_refuses_anything_but_his_150_whole_lessons() -> None:
    lessons = copy.deepcopy(dict(catalogue.bundled_lessons()))
    library.check(lessons)
    with pytest.raises(library.LibraryError, match="missing"):
        library.check({code: lesson for code, lesson in lessons.items() if code != "PB03"})
    with pytest.raises(library.LibraryError, match="unknown"):
        library.check({**lessons, "ZZ99": lessons["PB03"]})
    broken = copy.deepcopy(lessons)
    broken["PB03"]["cue"] = ""
    with pytest.raises(library.LibraryError, match="PB03"):
        library.check(broken)
    broken = copy.deepcopy(lessons)
    broken["PB03"]["next"] = ["ZZ99"]
    with pytest.raises(library.LibraryError, match="not Dipak's"):
        library.check(broken)


async def _rows(setup: Any) -> int:
    async with setup.sessions() as db:
        return int(
            await db.scalar(select(func.count()).select_from(SalesXrayAskDipakLibraryVersion)) or 0
        )


def test_an_import_reaches_the_app_without_a_release_and_never_the_lock(
    postgres_harness: Any, tmp_path: Path
) -> None:
    script = _load(SCRIPT, "ask_dipak_import_lessons")
    bundled = copy.deepcopy(dict(catalogue.bundled_lessons()))
    edited = copy.deepcopy(bundled)
    edited["PB03"]["cue"] = "Dipak का नया cue।"
    edited["PB03"]["title"] = "Customer कहता है price high है, अब?"

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        tenant = setup.state.tenant_id
        try:
            install_ask_dipak_coaching_http(
                setup.app, RouteContext(setup.settings, setup.require_actor, setup.sessions)
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)

                # Before any import: the bundled library, with its version.
                first = (await http.get(f"{BASE}/lessons/PB03")).json()
                assert first["version"] == library.bundled().version
                assert first["lesson"]["remember"] == bundled["PB03"]["cue"]
                assert first["lesson"]["mindset_shift"]["after"] == bundled["PB03"]["after"]

                # The bundle itself changes nothing: no row, no audit event.
                async with setup.sessions() as db, db.begin():
                    same = await script.change(
                        db,
                        lessons=bundled,
                        source={"docs": {}},
                        approver="Test Owner",
                        issue="TEST-1",
                        operations_tenant_id=tenant,
                        apply=True,
                        now=NOW,
                    )
                assert same["unchanged"] is True and same["applied"] is False
                assert await _rows(setup) == 0

                # A dry run of Dipak's edit says what would change and writes nothing.
                async with setup.sessions() as db, db.begin():
                    dry = await script.change(
                        db,
                        lessons=edited,
                        source={"docs": {"01.txt": "0" * 64}},
                        approver="Test Owner",
                        issue="TEST-1",
                        operations_tenant_id=tenant,
                        apply=False,
                        now=NOW,
                    )
                assert dry["changed_lessons"] == ["PB03"] and dry["applied"] is False
                assert dry["before"]["from"] == "bundled"
                assert await _rows(setup) == 0

                # Applied: one row and one audit event naming the approver and the issue.
                for _ in range(2):
                    async with setup.sessions() as db, db.begin():
                        done = await script.change(
                            db,
                            lessons=edited,
                            source={"docs": {"01.txt": "0" * 64}},
                            approver="Test Owner",
                            issue="TEST-1",
                            operations_tenant_id=tenant,
                            apply=True,
                            now=NOW,
                        )
                assert done["unchanged"] is True  # the second run found it already there
                assert await _rows(setup) == 1
                async with setup.sessions() as db:
                    event = (
                        await db.scalars(
                            select(AuditEvent).where(
                                AuditEvent.action == "ask_dipak.library_imported"
                            )
                        )
                    ).one()
                    assert event.payload["approver"] == "Test Owner"
                    assert event.payload["issue"] == "TEST-1"
                    assert event.payload["changed_lessons"] == ["PB03"]

                # The app teaches the edit at once, with the new version; never the lock.
                second = (await http.get(f"{BASE}/lessons/PB03")).json()
                assert second["version"] == dry["after"]["version"] != first["version"]
                assert second["lesson"]["remember"] == "Dipak का नया cue।"
                assert second["lesson"]["title"] == "Customer कहता है price high है, अब?"
                text = str(second)
                assert all(line not in text for line in edited["PB03"]["lock"])
                other = (await http.get(f"{BASE}/lessons/DM02")).json()
                assert other["lesson"]["remember"] == bundled["DM02"]["cue"]
        finally:
            catalogue.use_lessons(catalogue.bundled_lessons())
            await setup.engine.dispose()

    run(exercise())
