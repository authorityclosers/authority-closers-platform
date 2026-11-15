"""Ask Dipak's coaching loop on PostgreSQL (13 Nov 2026 meeting, section 5; migration 0155).

A seller ticks Next-call missions, keeps up to three active, and after each call from a lead
answers yes or no per active mission; answering again supersedes, never overwrites. The counts
per mission are the calls whose answer stands at yes. A seller answers only their own calls,
by the lead's call event or the analysed call (one answer either way). Owners and managers read
every seller's counts in their workspace; a seller cannot. Unticking drops a mission; erasing an
account takes its history. Disposable loopback PostgreSQL, fictional people and leads.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.ask_dipak import coaching, store, team
from ac_platform.ask_dipak.coaching_http import install_ask_dipak_coaching_http
from ac_platform.ask_dipak.coaching_models import SalesXrayAskDipakCallCheck
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

ROOT = Path(__file__).resolve().parents[2]
FILE = "20261115_0155_sales_xray_ask_dipak_coaching.py"
WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/sales-xray/ask-dipak"
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("sales_xray_ask_dipak_coaching_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_schema_gate_and_forward_recovery_with_history() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == ("20261115_0155", "20261115_0154")
    path = Path(module.__file__)
    check_operations([classify_source(path.read_text(), str(path))], set())
    module.op = SimpleNamespace(
        execute=lambda statement: None,
        get_bind=lambda: SimpleNamespace(scalar=lambda statement: True),
    )
    with pytest.raises(RuntimeError, match="history requires forward recovery"):
        module.downgrade()


async def _person(setup: Any, name: str, *, role: str | None) -> UUID:
    person_id = uuid4()
    async with setup.sessions() as db, db.begin():
        db.add(
            Person(
                id=person_id,
                email=f"{name.lower()}-{person_id.hex[:8]}@example.test",
                display_name=f"{name} Fictional",
                email_verified_at=NOW,
            )
        )
        await db.flush()
        if role is not None:
            db.add(
                Membership(
                    tenant_id=setup.state.tenant_id,
                    person_id=person_id,
                    role=role,
                    status="active",
                )
            )
    return person_id


async def _call(setup: Any, seller: UUID, *, minutes_ago: int, submission: UUID | None = None):
    """A lead and one call to it by this seller; returns (lead id, call event id)."""
    lead_id, event_id = uuid4(), uuid4()
    at = NOW - timedelta(minutes=minutes_ago)
    async with setup.sessions() as db, db.begin():
        db.add(
            Lead(
                id=lead_id,
                tenant_id=setup.state.tenant_id,
                revision=1,
                source="manual",
                payload={},
                name=f"Fictional Lead {minutes_ago}",
                stage="interested",
                attempts=1,
                calls=1,
                repeats=0,
                owner_person_id=seller,
                assigned_at=at,
                last_submission_id=submission,
                test_data=False,
                created_at=at,
                updated_at=at,
            )
        )
        await db.flush()
        db.add(
            LeadEvent(
                id=event_id,
                tenant_id=setup.state.tenant_id,
                lead_id=lead_id,
                kind="call",
                actor_person_id=seller,
                data={"submission_id": str(submission) if submission else None},
                created_at=at,
            )
        )
    return lead_id, event_id


async def _tick(setup: Any, seller: UUID, *codes: str) -> None:
    async with setup.sessions() as db, db.begin():
        for code in codes:
            await store.set_item(
                db,
                person_id=seller,
                tenant_id=setup.state.tenant_id,
                question_id=code,
                item="mission",
                on=True,
                now=NOW,
            )


def test_missions_active_answers_counts_and_the_team_read(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        tenant = setup.state.tenant_id
        try:
            seller = await _person(setup, "Priya", role="member")
            manager = await _person(setup, "Meera", role="manager")
            other = await _person(setup, "Ravi", role="member")

            # Only a ticked mission can be active, and three at most.
            async with setup.sessions() as db, db.begin():
                with pytest.raises(coaching.NotTicked):
                    await coaching.set_active(
                        db,
                        person_id=seller,
                        tenant_id=tenant,
                        question_id="PB03",
                        on=True,
                        now=NOW,
                    )
                with pytest.raises(store.NoMission):
                    await coaching.set_active(
                        db,
                        person_id=seller,
                        tenant_id=tenant,
                        question_id="PB05",
                        on=True,
                        now=NOW,
                    )
            await _tick(setup, seller, "PB03", "OB03", "DM02", "NX02")
            async with setup.sessions() as db, db.begin():
                for code in ("PB03", "OB03", "DM02"):
                    await coaching.set_active(
                        db,
                        person_id=seller,
                        tenant_id=tenant,
                        question_id=code,
                        on=True,
                        now=NOW,
                    )
                with pytest.raises(coaching.TooManyActive):
                    await coaching.set_active(
                        db,
                        person_id=seller,
                        tenant_id=tenant,
                        question_id="NX02",
                        on=True,
                        now=NOW,
                    )
                assert await coaching.active_missions(db, seller) == ("PB03", "OB03", "DM02")

            # Unticking a mission drops it from the active three.
            async with setup.sessions() as db, db.begin():
                await store.set_item(
                    db,
                    person_id=seller,
                    tenant_id=tenant,
                    question_id="DM02",
                    item="mission",
                    on=False,
                    now=NOW,
                )
                assert await coaching.active_missions(db, seller) == ("PB03", "OB03")

            # A call from a lead, answered by its call event; the analysed call is the same one.
            submission = uuid4()
            async with setup.sessions() as db, db.begin():
                db.add(
                    ConversationAcquisitionUsage(
                        id=uuid4(),
                        tenant_id=tenant,
                        person_id=seller,
                        submission_id=submission,
                        source_sha256="a" * 64,
                        duration_evidence_sha256="b" * 64,
                        reserved_seconds=60,
                        policy_revision="fictional",
                        created_at=NOW,
                    )
                )
            lead_one, event_one = await _call(setup, seller, minutes_ago=30, submission=submission)
            _, event_two = await _call(setup, seller, minutes_ago=10)
            _, ravis = await _call(setup, other, minutes_ago=5)

            async with setup.sessions() as db, db.begin():
                assert (
                    await coaching.resolve_call(
                        db, person_id=seller, tenant_id=tenant, call_id=ravis
                    )
                    is None
                )
                by_event = await coaching.resolve_call(
                    db, person_id=seller, tenant_id=tenant, call_id=event_one
                )
                by_call = await coaching.resolve_call(
                    db, person_id=seller, tenant_id=tenant, call_id=submission
                )
                assert by_event is not None and by_call is not None
                assert by_event.key == by_call.key == event_one
                assert (by_call.lead_id, by_call.submission_id) == (lead_one, submission)

                # Asked about each active mission; only those can be answered.
                asked = await coaching.call_check(db, person_id=seller, call=by_event)
                assert [m["question_id"] for m in asked["missions"]] == ["PB03", "OB03"]
                assert all(m["done"] is None for m in asked["missions"])
                with pytest.raises(coaching.NotAsked):
                    await coaching.record_answers(
                        db, person_id=seller, call=by_event, answers=[("NX02", True)], now=NOW
                    )
                await coaching.record_answers(
                    db,
                    person_id=seller,
                    call=by_event,
                    answers=[("PB03", True), ("OB03", False)],
                    now=NOW,
                )
                # The same answer again adds nothing; a change supersedes, by either ID.
                await coaching.record_answers(
                    db,
                    person_id=seller,
                    call=by_call,
                    answers=[("PB03", True)],
                    now=NOW + timedelta(minutes=1),
                )
                await coaching.record_answers(
                    db,
                    person_id=seller,
                    call=by_call,
                    answers=[("OB03", True)],
                    now=NOW + timedelta(minutes=2),
                )
                second = await coaching.resolve_call(
                    db, person_id=seller, tenant_id=tenant, call_id=event_two
                )
                assert second is not None
                await coaching.record_answers(
                    db,
                    person_id=seller,
                    call=second,
                    answers=[("PB03", False)],
                    now=NOW + timedelta(minutes=3),
                )

            async with setup.sessions() as db:
                rows = await db.scalar(select(func.count()).select_from(SalesXrayAskDipakCallCheck))
                assert rows == 4
                recent = await coaching.recent_calls(db, person_id=seller, tenant_id=tenant)
                assert [call["call_id"] for call in recent] == [str(event_two), str(event_one)]
                assert recent[0]["waiting"] == ["OB03"] and recent[1]["waiting"] == []
                grown = await coaching.my_growth(db, person_id=seller)
                missions = {m["question_id"]: m for m in grown["missions"]}
                assert grown["active"] == ["PB03", "OB03"]
                assert (missions["PB03"]["done_calls"], missions["PB03"]["not_done_calls"]) == (
                    1,
                    1,
                )
                assert (missions["OB03"]["done_calls"], missions["OB03"]["not_done_calls"]) == (
                    1,
                    0,
                )
                assert missions["NX02"]["ticked"] and not missions["NX02"]["active"]
                assert "DM02" not in missions

                # The manager reads every seller's counts here; a seller can't.
                read = await team.team_counts(db, tenant_id=tenant, viewer_id=manager)
                people = {row["person_id"]: row for row in read["people"]}
                priya = {m["question_id"]: m for m in people[str(seller)]["missions"]}
                assert priya["PB03"]["done_calls"] == 1 and people[str(other)]["missions"] == []
                with pytest.raises(team.NotTeamViewer):
                    await team.team_counts(db, tenant_id=tenant, viewer_id=seller)

            # Over HTTP: the app's pages only, the seller's own calls only.
            install_ask_dipak_coaching_http(
                setup.app, RouteContext(setup.settings, setup.require_actor, setup.sessions)
            )
            me = setup.state.person_id
            await _tick(setup, me, "TP03")
            _, mine = await _call(setup, me, minutes_ago=1)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)
                found = (await http.get(f"{BASE}/lessons", params={"q": "mahanga"})).json()
                assert found["questions"][0]["id"] == "PB03"
                lesson = (await http.get(f"{BASE}/lessons/PB03")).json()
                assert lesson["lesson"]["next_call_mission"].startswith("अगली तीन price")
                assert "coach" not in str(lesson)
                improve = await http.get(
                    f"{BASE}/how-to-improve",
                    params={"skills": "closing_decision_management", "objections": "stall"},
                )
                assert [q["id"] for q in improve.json()["questions"]][:2] == ["NX02", "OB03"]
                assert (
                    await http.put(f"{BASE}/focus/TP03", json={"active": True})
                ).status_code == 403
                active = await http.put(f"{BASE}/focus/TP03", json={"active": True}, headers=WRITE)
                assert active.status_code == 200, active.text
                assert active.json()["active"] == ["TP03"]
                calls = (await http.get(f"{BASE}/calls")).json()
                assert calls["calls"][0]["call_id"] == str(mine)
                assert (await http.get(f"{BASE}/calls/{ravis}/check")).status_code == 404
                answered = await http.put(
                    f"{BASE}/calls/{mine}/check",
                    json={"answers": [{"question_id": "TP03", "done": True}]},
                    headers=WRITE,
                )
                assert answered.status_code == 200, answered.text
                assert answered.json()["missions"][0]["done"] is True
                growth = (await http.get(f"{BASE}/growth")).json()
                assert growth["missions"][0]["done_calls"] == 1

            # An erased account takes its missions and answers, and only its own.
            async with setup.sessions() as db, db.begin():
                assert await coaching.erase_coaching_for_person(db, person_id=seller) == 8
            async with setup.sessions() as db:
                assert await coaching.active_missions(db, seller) == ()
                assert (await coaching.my_growth(db, person_id=me))["active"] == ["TP03"]
        finally:
            await setup.engine.dispose()

    run(exercise())
