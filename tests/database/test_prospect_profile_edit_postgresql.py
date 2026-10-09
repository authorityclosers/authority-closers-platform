"""Fictional authenticated name edits on disposable loopback PostgreSQL."""

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import event, select, text, update

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.prospect_models import ConversationProspect
from ac_platform.conversation_intelligence.prospect_store import ProspectStore
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed, wait_blocked
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_prospect_library_postgresql import snapshot
from tests.database.test_prospect_store_postgresql import direct_call, store

PREFIX = "/v1/conversation/prospects"
BODY = {"display_name": "Mehta Example Updated", "expected_revision": 1}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def client_for(setup: Any) -> httpx.AsyncClient:
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=setup.app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
    )
    client.cookies.set(setup.settings.session_cookie_name, setup.token)
    return client


async def state(setup: Any, prospect_id: str) -> Any:
    async with setup.sessions() as db:
        row = await db.get(ConversationProspect, UUID(prospect_id))
        events = (await db.scalars(select(AuditEvent).order_by(AuditEvent.id))).all()
        return (
            row.display_name,
            row.revision,
            row.updated_at,
            [(e.id, e.event_hash) for e in events],
        )


def private(response: httpx.Response, status: int) -> None:
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"


def test_name_edit_reads_concurrency_noop_rollback_and_constant_queries(
    postgres_harness: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        statements: list[str] = []

        def count(*args: Any) -> None:
            statements.append(args[2])

        try:
            call = await direct_call(setup)
            await snapshot(setup, call)
            async with client_for(setup) as client:
                created = await client.post(
                    f"{PREFIX}/calls/{call}/create", json={"display_name": "Mehta Example"}
                )
                assert created.status_code == 201
                identifier = created.json()["membership"]["prospect_id"]
                companion = await direct_call(setup)
                assert (
                    await client.post(
                        f"{PREFIX}/calls/{companion}/create",
                        json={"display_name": "Mehta ab Updated"},
                    )
                ).status_code == 201
                path = f"{PREFIX}/{identifier}"
                before = (await client.get(path)).json()
                persisted = await state(setup, identifier)
                setup.clock[0] += timedelta(seconds=1)
                response = await client.patch(
                    path, json={**BODY, "display_name": "  Mehta %_ Updated  "}
                )
                private(response, 200)
                assert response.json() == {
                    "schema": "ac.sales-xray.prospect-name/1",
                    "prospect": {
                        "prospect_id": identifier,
                        "name": "Mehta %_ Updated",
                        "revision": 2,
                    },
                }
                saved = await state(setup, identifier)
                assert saved[:3] == ("Mehta %_ Updated", 2, setup.clock[0])
                assert len(saved[3]) == len(persisted[3]) + 1
                after = (await client.get(path)).json()
                assert after["calls"] == before["calls"]
                assert after["prospect"] == {
                    **before["prospect"],
                    "name": "Mehta %_ Updated",
                    "revision": 2,
                }
                assert after["prospect"]["contact"] is after["prospect"]["photo_url"] is None
                for search, total in [("%_", 1), ("Mehta Example", 0)]:
                    page = (await client.get(PREFIX, params={"search": search})).json()
                    assert page["total"] == total
                    if total:
                        assert page["prospects"][0]["name"] == "Mehta %_ Updated"
                concurrent = await asyncio.gather(
                    *[
                        client.patch(path, json={"display_name": name, "expected_revision": 2})
                        for name in ["Fictional First", "Fictional Second"]
                    ]
                )
                assert sorted(r.status_code for r in concurrent) == [200, 409]
                winner = next(r.json()["prospect"] for r in concurrent if r.status_code == 200)
                saved = await state(setup, identifier)
                assert saved[1] == 3 and len(saved[3]) == len(persisted[3]) + 2
                setup.clock[0] += timedelta(seconds=1)
                noop = await client.patch(
                    path, json={"display_name": " " + winner["name"], "expected_revision": 3}
                )
                private(noop, 200)
                assert noop.json()["prospect"] == winner
                stale = await client.patch(
                    path, json={"display_name": winner["name"], "expected_revision": 2}
                )
                private(stale, 409)
                assert "The prospect changed. Reload before saving again." in stale.text
                assert await state(setup, identifier) == saved

                async def fail_audit(*args: Any, **kwargs: Any) -> None:
                    raise RuntimeError("Fictional audit failure")

                with monkeypatch.context() as patch:
                    patch.setattr(ProspectStore, "_audit", fail_audit)
                    with pytest.raises(RuntimeError, match="Fictional audit failure"):
                        await client.patch(
                            path, json={"display_name": "Rolled back", "expected_revision": 3}
                        )
                assert await state(setup, identifier) == saved
                event.listen(setup.engine.sync_engine, "before_cursor_execute", count)
                counts = []
                for size, revision in [(1, 3), (25, 4)]:
                    if size == 25:
                        for _ in range(24):
                            extra = await direct_call(setup)
                            async with setup.sessions() as db, db.begin():
                                await store(setup, db).confirm_link(
                                    setup.state.actor,
                                    extra,
                                    UUID(identifier),
                                    expected_membership_id=None,
                                )
                    statements.clear()
                    private(
                        await client.patch(
                            path,
                            json={
                                "display_name": f"Fictional {size}",
                                "expected_revision": revision,
                            },
                        ),
                        200,
                    )
                    counts.append(len(statements))
                    assert (await client.get(path)).json()["prospect"]["call_count"] == size
                assert counts[0] == counts[1]
                print(f"name-edit SQL statements (1/25 memberships): {counts}")
                async with setup.sessions() as db:
                    changes = (
                        await db.scalars(
                            select(AuditEvent)
                            .where(AuditEvent.action == "conversation.prospect_name_changed")
                            .order_by(AuditEvent.sequence_no)
                        )
                    ).all()
                    assert len(changes) == 4
                    for revision, change in enumerate(changes, start=1):
                        assert change.payload == {
                            "field": "display_name",
                            "previous_revision": str(revision),
                            "current_revision": str(revision + 1),
                        }
                        assert change.actor_person_id == setup.state.person_id
                        assert change.session_id == setup.state.actor.session_id
                        assert change.tenant_id == setup.state.tenant_id
                        assert change.resource_id == identifier
                    assert (await verify_audit_chain(db, setup.state.tenant_id)).valid
        finally:
            if event.contains(setup.engine.sync_engine, "before_cursor_execute", count):
                event.remove(setup.engine.sync_engine, "before_cursor_execute", count)
            await setup.engine.dispose()

    run(exercise())


def test_rejected_name_edits_preserve_storage_and_audit(
    postgres_harness: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            call = await direct_call(setup)
            async with client_for(setup) as client:
                created = await client.post(
                    f"{PREFIX}/calls/{call}/create", json={"display_name": "Mehta Example"}
                )
                identifier = created.json()["membership"]["prospect_id"]
                path = f"{PREFIX}/{identifier}"
                before = await state(setup, identifier)
                invalid = [
                    {**BODY, "display_name": value}
                    for value in ["", "  ", "x" * 161, 1, None, False]
                ]
                invalid += [
                    {**BODY, "expected_revision": value} for value in [0, -1, True, "1", 1.5, None]
                ]
                invalid += [{"display_name": "Fictional"}, {"expected_revision": 1}]
                invalid += [
                    {**BODY, key: str(uuid4())}
                    for key in [
                        "person_id",
                        "tenant_id",
                        "owner_person_id",
                        "call_id",
                        "stage",
                        "tags",
                    ]
                ]
                for body in invalid:
                    private(await client.patch(path, json=body), 422)
                    assert await state(setup, identifier) == before
                for suffix in [
                    "?tenant_id=x",
                    "?expected_revision=1",
                    "?offset=0",
                    "?offset=0&offset=1",
                ]:
                    private(await client.patch(path + suffix, json=BODY), 422)
                private(await client.patch(PREFIX + "/invalid-id", json=BODY), 422)
                private(await client.patch(f"{PREFIX}/{uuid4()}", json=BODY), 404)
                for origin in ["", "https://evil.example.test"]:
                    private(await client.patch(path, json=BODY, headers={"Origin": origin}), 403)
                private(await client.patch("https://learner.example.test" + path, json=BODY), 404)
                private(
                    await client.patch(path, content=b"{}", headers={"content-type": "text/plain"}),
                    415,
                )
                for raw, status in [(b"x" * 2049, 413), (b"{", 422)]:
                    private(
                        await client.patch(
                            path, content=raw, headers={"content-type": "application/json"}
                        ),
                        status,
                    )

                async def timed_out(_request: Any) -> Any:
                    raise TimeoutError
                    yield b""  # pragma: no cover

                from starlette.requests import Request

                with monkeypatch.context() as patch:
                    patch.setattr(Request, "stream", timed_out)
                    private(await client.patch(path, json=BODY), 408)
                client.cookies.clear()
                private(await client.patch(path, json=BODY), 401)
                client.cookies.set(setup.settings.session_cookie_name, "invalid")
                private(await client.patch(path, json=BODY), 401)
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                other = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
                foreign = await seed(setup.engine)
                client.cookies.set(setup.settings.session_cookie_name, await _session(setup, other))
                private(await client.patch(path, json=BODY), 404)
                async with setup.sessions() as db, db.begin():
                    db.add(
                        Organisation(
                            tenant_id=setup.state.tenant_id,
                            created_by_person_id=other.person_id,
                            creation_command_id=uuid4(),
                            domain_verification_token="fictional-token-" * 4,
                        )
                    )
                    await db.execute(
                        update(Membership)
                        .where(
                            Membership.tenant_id == setup.state.tenant_id,
                            Membership.person_id == other.person_id,
                        )
                        .values(role="admin")
                    )
                assert (await client.get(path)).status_code == 200
                private(await client.patch(path, json=BODY), 404)
                async with setup.sessions() as db, db.begin():
                    foreign_id = uuid4()
                    db.add(
                        ConversationProspect(
                            id=foreign_id,
                            tenant_id=foreign.tenant_id,
                            display_name="Foreign Example",
                            created_by_person_id=foreign.person_id,
                            owner_person_id=foreign.person_id,
                            revision=1,
                            created_at=foreign.now,
                            updated_at=foreign.now,
                        )
                    )
                private(await client.patch(f"{PREFIX}/{foreign_id}", json=BODY), 404)
                client.cookies.set(
                    setup.settings.session_cookie_name, await _session(setup, foreign)
                )
                private(await client.patch(path, json=BODY), 403)
                assert await state(setup, identifier) == before
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_waiting_edit_refreshes_cached_row_after_lock(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            call = await direct_call(setup)
            async with setup.sessions() as db, db.begin():
                row = await store(setup, db).create_from_call(
                    setup.state.actor, call, display_name="Cached Fictional"
                )
                identifier = row.id
            async with setup.sessions() as first, setup.sessions() as second:
                await first.begin()
                await second.begin()
                service = store(setup, second)
                cached = await service.read(setup.state.actor, identifier)
                assert cached.revision == 1
                await store(setup, first).edit_name(setup.state.actor, identifier, **BODY)
                pid = await second.scalar(text("SELECT pg_backend_pid()"))
                pending = asyncio.create_task(
                    service.edit_name(
                        setup.state.actor,
                        identifier,
                        display_name="Competing Fictional",
                        expected_revision=1,
                    )
                )
                try:
                    await wait_blocked(setup.engine, pid, pending)
                    await first.commit()
                    with pytest.raises(ConversationConflict):
                        await pending
                    assert cached.revision == 2 and cached.display_name == BODY["display_name"]
                finally:
                    if not pending.done():
                        pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                    await second.rollback()
            assert (await state(setup, str(identifier)))[:2] == (BODY["display_name"], 2)
        finally:
            await setup.engine.dispose()

    run(exercise())
