"""Ask Dipak's lesson videos behind one server switch, OFF until approved, on PostgreSQL (owner,
19 Nov 2026 23:36 IST: "the videos are not approved for Ask Dipak, so make sure they won't go
live on the app in the next update"; v1.88 showed them with no switch and was rolled back).

With no data step the app is sent no video. The admin CLI (scripts/data-changes/admin.py
``ask-dipak videos on|off``, ``add-video``, ``remove-video``) changes it as an owner-approved
data change: a dry run rolls back, an apply appends Dipak's lessons again with the videos and
one audit event, the same command replays. A video added while the switch is off is not sent;
switching off sends none again. A new import of Dipak's docs keeps the videos. The lessons and
their version never change. Disposable loopback PostgreSQL; fictional people and addresses.
"""

from __future__ import annotations

import copy
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from ac_platform.ask_dipak import catalogue, library, videos
from ac_platform.ask_dipak.coaching_http import install_ask_dipak_coaching_http
from ac_platform.ask_dipak.models import SalesXrayAskDipakLibraryVersion
from ac_platform.audit.models import AuditEvent
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

ROOT = Path(__file__).resolve().parents[2]
BASE = "/v1/sales-xray/ask-dipak"
NOW = datetime(2026, 11, 20, 6, 0, tzinfo=UTC)
PB03 = {
    "src": "/dev-media/ask-dipak/lessons/pb03-lesson.mp4",
    "poster": "/dev-media/ask-dipak/lessons/pb03-lesson-poster.jpg",
    "seconds": 61,
}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _admin() -> Any:
    spec = importlib.util.spec_from_file_location(
        "admin_cli_videos", ROOT / "scripts/data-changes/admin.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_video_is_checked_before_it_is_kept() -> None:
    assert videos.check_video("PB03", PB03["src"], PB03["poster"], 61) == PB03
    for bad in (
        ("ZZ99", PB03["src"], PB03["poster"], 61),
        ("PB03", "//evil.test/x.mp4", PB03["poster"], 61),
        ("PB03", "http://plain.test/x.mp4", PB03["poster"], 61),
        ("PB03", "/a/../x.mp4", PB03["poster"], 61),
        ("PB03", PB03["src"], "/x.gif", 61),
        ("PB03", PB03["src"], PB03["poster"], 0),
        ("PB03", PB03["src"], PB03["poster"], True),
    ):
        with pytest.raises(videos.VideoError):
            videos.check_video(*bad)
    # Anything unreadable in a stored row is OFF.
    assert videos.state_of(None) == {"enabled": False, "videos": {}}
    assert videos.state_of({library.VIDEOS: {"enabled": "yes", "videos": {"PB03": PB03}}}) == {
        "enabled": False,
        "videos": {"PB03": PB03},
    }
    assert videos.state_of({library.VIDEOS: {"enabled": True, "videos": {"PB03": 1}}}) == {
        "enabled": True,
        "videos": {},
    }


def test_videos_stay_off_until_switched_on_and_each_is_added_by_the_cli(
    postgres_harness: Any, tmp_path: Path
) -> None:
    tool = _admin()

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        operator = setup.state.person_id
        async with setup.sessions() as db, db.begin():
            await db.execute(
                update(Person).where(Person.id == operator).values(email_verified_at=NOW)
            )
        settings = setup.settings.model_copy(
            update={
                "operations_tenant_id": setup.state.tenant_id,
                "public_learner_tenant_id": uuid4(),
            }
        )

        async def cli(*argv: str, apply: bool = False, write: bool = True) -> Any:
            given = [*argv, "--environment", "development"]
            if write:
                given += [
                    "--actor-person-id",
                    str(operator),
                    "--approver",
                    "owner-chat-20261119",
                    "--issue",
                    "orch:askdipak-videos-off-20261120",
                ]
            if apply:
                given.append("--apply")
            return await tool.execute(setup.sessions, settings, tool.parse(given))

        async def rows() -> int:
            async with setup.sessions() as db:
                return int(
                    await db.scalar(
                        select(func.count()).select_from(SalesXrayAskDipakLibraryVersion)
                    )
                    or 0
                )

        async def audits() -> int:
            async with setup.sessions() as db:
                return int(
                    await db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.action == tool.ACTION)
                    )
                    or 0
                )

        add = ("ask-dipak", "add-video", "--lesson", "PB03", "--src", PB03["src"])
        add += ("--poster", PB03["poster"], "--seconds", "61")
        try:
            install_ask_dipak_coaching_http(
                setup.app, RouteContext(setup.settings, setup.require_actor, setup.sessions)
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)

                async def sent() -> dict[str, Any]:
                    answer = await http.get(f"{BASE}/videos")
                    assert answer.status_code == 200
                    assert answer.headers["cache-control"] == "private, no-store"
                    return cast(dict[str, Any], answer.json()["videos"])

                # No data step (a new staging or production): no video, and the switch reads off.
                assert await sent() == {}
                read = await cli("ask-dipak", "videos", write=False)
                assert read["mode"] == "read"
                assert read["lesson_videos"] == {"enabled": False, "videos": {}}
                version = (await http.get(f"{BASE}/lessons/PB03")).json()["version"]

                # A dry run of adding PB03's video rolls back: no row, no audit.
                dry = await cli(*add)
                assert dry["mode"] == "dry_run" and dry["rolled_back"] is True
                assert dry["after"]["videos"] == {"PB03": PB03}
                assert (await rows(), await audits()) == (0, 0)

                # Applied while the switch is off: kept, audited, still not sent.
                done = await cli(*add, apply=True)
                assert done["status"] == "applied" and done["audit"] == "written"
                assert (await rows(), await audits()) == (1, 1)
                assert await sent() == {}
                again = await cli(*add, apply=True)
                assert again["status"] == "replayed"
                assert (await rows(), await audits()) == (1, 1)

                # Switched on: the approved video is sent; the lessons and their version stay.
                on = await cli("ask-dipak", "videos", "on", apply=True)
                assert on["status"] == "applied"
                assert on["before"]["enabled"] is False and on["after"]["enabled"] is True
                assert await sent() == {"PB03": PB03}
                assert (await http.get(f"{BASE}/lessons/PB03")).json()["version"] == version

                # A new import of Dipak's docs keeps the switch and the videos.
                edited = copy.deepcopy(dict(catalogue.bundled_lessons()))
                edited["DM02"]["cue"] = "Dipak का नया cue।"
                async with setup.sessions() as db, db.begin():
                    imported = await library.record_import(
                        db,
                        lessons=edited,
                        source={"docs": {}},
                        approved_by="Test Owner",
                        issue="TEST-2",
                        now=datetime.now(UTC),
                        apply=True,
                    )
                assert imported["applied"] is True
                assert await sent() == {"PB03": PB03}

                # Removed, then off: none sent again.
                gone = await cli("ask-dipak", "remove-video", "--lesson", "PB03", apply=True)
                assert gone["after"] == {"enabled": True, "videos": {}}
                assert await sent() == {}
                await cli(*add, "--command-id", str(uuid4()), apply=True)
                assert await sent() == {"PB03": PB03}
                off = await cli("ask-dipak", "videos", "off", apply=True)
                assert off["after"]["enabled"] is False
                assert await sent() == {}

                # Nothing to do still keeps its receipt; a bad address is refused, nothing kept.
                same = await cli(
                    "ask-dipak", "videos", "off", "--command-id", str(uuid4()), apply=True
                )
                assert same["status"] == "already_set"
                count = await rows()
                with pytest.raises(tool.OrganisationCommandError):
                    await cli(
                        "ask-dipak",
                        "add-video",
                        "--lesson",
                        "OB03",
                        "--src",
                        "//x.test/a.mp4",
                        "--poster",
                        PB03["poster"],
                        "--seconds",
                        "55",
                        apply=True,
                    )
                assert await rows() == count
        finally:
            catalogue.use_lessons(catalogue.bundled_lessons())
            await setup.engine.dispose()

    run(exercise())
