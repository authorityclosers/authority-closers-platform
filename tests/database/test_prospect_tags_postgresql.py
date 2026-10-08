"""Fictional tags writes, shared revision races and populated loopback upgrade."""

import asyncio
import json
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import event, select, text, update
from starlette.requests import Request

import ac_platform.http.conversation_prospects as prospect_http
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.prospect_models import (
    ConversationProspect,
    ConversationProspectMembership,
)
from ac_platform.conversation_intelligence.prospect_store import ProspectStore
from ac_platform.db.models import model_metadata
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed, wait_blocked
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_prospect_library_postgresql import snapshot
from tests.database.test_prospect_profile_edit_postgresql import PREFIX, client_for, private
from tests.database.test_prospect_store_postgresql import direct_call, store

BODY = {"tags": ["QA label", "Follow up"], "expected_revision": 1}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def state(setup: Any, identifier: str) -> Any:
    async with setup.sessions() as db:
        row = await db.get(ConversationProspect, UUID(identifier))
        events = (await db.scalars(select(AuditEvent).order_by(AuditEvent.id))).all()
        members = (await db.scalars(select(ConversationProspectMembership))).all()
        return (
            row.tags,
            row.revision,
            row.updated_at,
            row.display_name,
            row.owner_person_id,
            [(e.id, e.event_hash) for e in events],
            [(m.id, m.prospect_id, m.submission_id, m.ended_at) for m in members],
        )


async def create(setup: Any, client: Any) -> str:
    call = await direct_call(setup)
    await snapshot(setup, call)
    response = await client.post(
        f"{PREFIX}/calls/{call}/create", json={"display_name": "Mehta Example"}
    )
    assert response.status_code == 201
    return response.json()["membership"]["prospect_id"]


def test_tags_persistence_noop_shared_races_audit_rollback_and_queries(
    postgres_harness: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        statements: list[str] = []

        def count(*args: Any) -> None:
            statements.append(args[2])

        try:
            async with client_for(setup) as client:
                identifier = await create(setup, client)
                path, write = f"{PREFIX}/{identifier}", f"{PREFIX}/{identifier}/tags"
                before = (await client.get(path)).json()
                initial = await state(setup, identifier)
                assert initial[0] == before["prospect"]["tags"] == []
                setup.clock[0] += timedelta(seconds=1)
                tags = ["हिन्दी", "日本語", "QA", "qa"]
                response = await client.patch(
                    write, json={**BODY, "tags": [f" {t} " for t in tags]}
                )
                private(response, 200)
                assert response.json() == {
                    "schema": "ac.sales-xray.prospect-tags/1",
                    "prospect": {"prospect_id": identifier, "tags": tags, "revision": 2},
                }
                saved = await state(setup, identifier)
                assert saved[:3] == (tags, 2, setup.clock[0]) and saved[3:5] == initial[3:5]
                assert saved[6] == initial[6]
                assert set(initial[5]) < set(saved[5]) and len(saved[5]) == len(initial[5]) + 1
                assert (await client.get(path)).json() == {
                    **before,
                    "prospect": {**before["prospect"], "tags": tags, "revision": 2},
                }
                assert (await client.get(PREFIX)).json()["prospects"][0]["tags"] == tags
                setup.clock[0] += timedelta(seconds=1)
                private(await client.patch(write, json={"tags": tags, "expected_revision": 2}), 200)
                stale = await client.patch(write, json={"tags": tags, "expected_revision": 1})
                private(stale, 409)
                assert stale.json()["detail"] == "The prospect changed. Reload before saving again."
                assert await state(setup, identifier) == saved
                private(await client.patch(write, json={"tags": [], "expected_revision": 2}), 200)
                cleared = await state(setup, identifier)
                assert cleared[0:2] == ([], 3) and len(cleared[5]) == len(initial[5]) + 2
                races = await asyncio.gather(
                    *[
                        client.patch(write, json={"tags": [tag], "expected_revision": 3})
                        for tag in ["First", "Second"]
                    ]
                )
                assert sorted(r.status_code for r in races) == [200, 409]
                winner = next(r.json()["prospect"]["tags"] for r in races if r.status_code == 200)
                races = await asyncio.gather(
                    client.patch(
                        path, json={"display_name": "Name winner", "expected_revision": 4}
                    ),
                    client.patch(write, json={"tags": ["Tags winner"], "expected_revision": 4}),
                )
                assert sorted(r.status_code for r in races) == [200, 409]
                saved = await state(setup, identifier)
                assert saved[1] == 5 and len(saved[5]) == len(initial[5]) + 4
                assert (saved[3], saved[0]) == (
                    ("Name winner", winner)
                    if races[0].status_code == 200
                    else (initial[3], ["Tags winner"])
                )

                async def fail_audit(*args: Any, **kwargs: Any) -> None:
                    raise RuntimeError("Fictional audit failure")

                with monkeypatch.context() as patch:
                    patch.setattr(ProspectStore, "_audit", fail_audit)
                    with pytest.raises(RuntimeError, match="Fictional audit failure"):
                        await client.patch(
                            write, json={"tags": ["Rollback"], "expected_revision": 5}
                        )
                assert await state(setup, identifier) == saved
                event.listen(setup.engine.sync_engine, "before_cursor_execute", count)
                measurements: dict[str, list[int]] = {"write": [], "list": [], "detail": []}
                for size, revision in [(1, 5), (20, 6), (25, 7)]:
                    if size > 1:
                        for _ in range(19 if size == 20 else 5):
                            extra = await direct_call(setup)
                            async with setup.sessions() as db, db.begin():
                                await store(setup, db).confirm_link(
                                    setup.state.actor,
                                    extra,
                                    UUID(identifier),
                                    expected_membership_id=None,
                                )
                    if size == 20:
                        async with setup.sessions() as db, db.begin():
                            for i in range(19):
                                db.add(
                                    ConversationProspect(
                                        id=uuid4(),
                                        tenant_id=setup.state.tenant_id,
                                        display_name=f"Fictional {i}",
                                        created_by_person_id=setup.state.person_id,
                                        owner_person_id=setup.state.person_id,
                                        revision=1,
                                        created_at=setup.clock[0],
                                        updated_at=setup.clock[0],
                                    )
                                )
                    for kind, request in [
                        (
                            "write",
                            lambda size=size, revision=revision: client.patch(
                                write,
                                json={"tags": [f"Size {size}"], "expected_revision": revision},
                            ),
                        ),
                        ("list", lambda: client.get(PREFIX)),
                        ("detail", lambda: client.get(path)),
                    ]:
                        statements.clear()
                        response = await request()
                        measurements[kind].append(len(statements))
                        private(response, 200)
                        if kind == "list":
                            assert response.json()["total"] == (1 if size == 1 else 20)
                            assert all(
                                p["tags"] == []
                                for p in response.json()["prospects"]
                                if p["prospect_id"] != identifier
                            )
                        elif kind == "detail":
                            assert response.json()["prospect"]["call_count"] == size
                            assert response.json()["prospect"]["tags"] == [f"Size {size}"]
                assert all(len(set(counts)) == 1 for counts in measurements.values())
                print(f"tags SQL statements (1/20/25 calls; 1/20/20 prospects): {measurements}")
                async with setup.sessions() as db:
                    changes = (
                        await db.scalars(
                            select(AuditEvent)
                            .where(AuditEvent.action == "conversation.prospect_tags_changed")
                            .order_by(AuditEvent.sequence_no)
                        )
                    ).all()
                    assert len(changes) == (6 if races[0].status_code == 200 else 7)
                    for change in changes:
                        assert set(change.payload) == {
                            "field",
                            "previous_revision",
                            "current_revision",
                            "previous_tag_count",
                            "current_tag_count",
                        }
                        assert change.payload["field"] == "tags"
                        assert all(
                            value.isdigit()
                            for key, value in change.payload.items()
                            if key != "field"
                        )
                        assert (
                            int(change.payload["current_revision"])
                            == int(change.payload["previous_revision"]) + 1
                        )
                        assert (
                            change.actor_person_id,
                            change.session_id,
                            change.tenant_id,
                            change.resource_id,
                        ) == (
                            setup.state.person_id,
                            setup.state.actor.session_id,
                            setup.state.tenant_id,
                            identifier,
                        )
                    assert changes[0].payload["previous_tag_count"] == "0"
                    assert (
                        changes[0].payload["current_tag_count"]
                        == changes[1].payload["previous_tag_count"]
                        == "4"
                    )
                    assert changes[1].payload["current_tag_count"] == "0"
                    assert (await verify_audit_chain(db, setup.state.tenant_id)).valid
                fresh = await create(setup, client)
                assert (await client.get(f"{PREFIX}/{fresh}")).json()["prospect"]["tags"] == []
                maximum = [str(i) + "x" * 39 for i in range(10)]
                private(
                    await client.patch(
                        f"{PREFIX}/{fresh}/tags", json={"tags": maximum, "expected_revision": 1}
                    ),
                    200,
                )
                assert (await state(setup, fresh))[0] == maximum
        finally:
            if event.contains(setup.engine.sync_engine, "before_cursor_execute", count):
                event.remove(setup.engine.sync_engine, "before_cursor_execute", count)
            await setup.engine.dispose()

    run(exercise())


def test_rejected_tags_and_read_only_authority_preserve_state(
    postgres_harness: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    async def exercise() -> None:
        served: set[UUID] = set()
        install = prospect_http.install_prospect_http

        def fixture_workspaces(*args: Any, **kwargs: Any) -> None:
            served.update(kwargs.pop("served"))
            install(*args, **kwargs, served=served)

        with monkeypatch.context() as patch:
            patch.setattr(prospect_http, "install_prospect_http", fixture_workspaces)
            setup = await _setup(postgres_harness, tmp_path)
        try:
            async with client_for(setup) as client:
                identifier = await create(setup, client)
                path = f"{PREFIX}/{identifier}/tags"
                before = await state(setup, identifier)
                invalid = [
                    {**BODY, "tags": value}
                    for value in [
                        None,
                        "QA",
                        1,
                        {},
                        [None],
                        [False],
                        [1],
                        [""],
                        [" \t"],
                        ["x" * 41],
                        [str(i) for i in range(11)],
                        ["QA", " QA "],
                    ]
                ]
                invalid += [
                    {**BODY, "expected_revision": value} for value in [None, True, "1", 0, -1, 1.5]
                ]
                invalid += [{"tags": []}, {"expected_revision": 1}]
                invalid += [
                    {**BODY, key: str(uuid4())}
                    for key in [
                        "person_id",
                        "tenant_id",
                        "owner_person_id",
                        "call_id",
                        "display_name",
                        "stage",
                    ]
                ]
                for body in invalid:
                    private(await client.patch(path, json=body), 422)
                    assert await state(setup, identifier) == before
                for suffix in [
                    "?person_id=x",
                    "?tenant_id=x",
                    "?owner_person_id=x",
                    "?call_id=x",
                    "?offset=0&offset=1",
                ]:
                    private(await client.patch(path + suffix, json=BODY), 422)
                private(await client.patch(f"{PREFIX}/invalid/tags", json=BODY), 422)
                private(await client.patch(f"{PREFIX}/{uuid4()}/tags", json=BODY), 404)
                private(
                    await client.patch(
                        f"{PREFIX}/{identifier}", json={**BODY, "display_name": "No"}
                    ),
                    422,
                )
                for origin in ["", "https://evil.example.test"]:
                    private(await client.patch(path, json=BODY, headers={"Origin": origin}), 403)
                private(await client.patch("https://learner.example.test" + path, json=BODY), 404)
                private(
                    await client.patch(path, content=b"{}", headers={"content-type": "text/plain"}),
                    415,
                )
                for raw, status in [(b"{", 422), (b"x" * 2049, 413)]:
                    private(
                        await client.patch(
                            path, content=raw, headers={"content-type": "application/json"}
                        ),
                        status,
                    )
                # Escaped Unicode passes character bounds but exceeds the independent byte cap.
                private(
                    await client.patch(
                        path,
                        content=json.dumps(
                            {**BODY, "tags": [str(i) + "界" * 39 for i in range(10)]}
                        ).encode(),
                        headers={"content-type": "application/json"},
                    ),
                    413,
                )

                async def timed_out(_request: Any) -> Any:
                    raise TimeoutError
                    yield b""  # pragma: no cover

                with monkeypatch.context() as patch:
                    patch.setattr(Request, "stream", timed_out)
                    private(await client.patch(path, json=BODY), 408)
                client.cookies.clear()
                private(await client.patch(path, json=BODY), 401)
                client.cookies.set(setup.settings.session_cookie_name, "invalid")
                private(await client.patch(path, json=BODY), 401)
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
                assert (await client.get(f"{PREFIX}/{identifier}")).status_code == 200
                private(await client.patch(path, json=BODY), 404)
                client.cookies.set(
                    setup.settings.session_cookie_name, await _session(setup, foreign)
                )
                private(await client.patch(path, json=BODY), 403)  # unserved selected workspace
                served.add(foreign.tenant_id)
                private(await client.patch(path, json=BODY), 404)  # served foreign workspace
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                async with setup.sessions() as db, db.begin():
                    foreign_id, creator_id = uuid4(), uuid4()
                    for target, tenant, creator, owner in [
                        (foreign_id, foreign.tenant_id, foreign.person_id, foreign.person_id),
                        (creator_id, setup.state.tenant_id, setup.state.person_id, other.person_id),
                    ]:
                        db.add(
                            ConversationProspect(
                                id=target,
                                tenant_id=tenant,
                                display_name="Fictional read target",
                                created_by_person_id=creator,
                                owner_person_id=owner,
                                revision=1,
                                created_at=setup.clock[0],
                                updated_at=setup.clock[0],
                            )
                        )
                private(await client.patch(f"{PREFIX}/{foreign_id}/tags", json=BODY), 404)
                assert (await client.get(f"{PREFIX}/{creator_id}")).status_code == 200
                private(await client.patch(f"{PREFIX}/{creator_id}/tags", json=BODY), 404)
                assert await state(setup, identifier) == before
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_waiting_tags_refresh_cached_row_after_name_lock(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with client_for(setup) as client:
                identifier = UUID(await create(setup, client))
            async with setup.sessions() as first, setup.sessions() as second:
                await first.begin()
                await second.begin()
                service = store(setup, second)
                cached = await service.read(setup.state.actor, identifier)
                await store(setup, first).edit_name(
                    setup.state.actor, identifier, display_name="Fresh", expected_revision=1
                )
                pid = await second.scalar(text("SELECT pg_backend_pid()"))
                pending = asyncio.create_task(
                    service.edit_tags(setup.state.actor, identifier, **BODY)
                )
                try:
                    await wait_blocked(setup.engine, pid, pending)
                    await first.commit()
                    with pytest.raises(ConversationConflict):
                        await pending
                    assert (
                        cached.revision == 2
                        and cached.display_name == "Fresh"
                        and cached.tags == []
                    )
                finally:
                    if not pending.done():
                        pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                    await second.rollback()
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_populated_0076_upgrade_preserves_identity_history_and_model(
    tmp_path: Path, monkeypatch: Any
) -> None:
    original = subprocess.run
    invocation: list[Any] = []

    def parent_first(args: Any, **kwargs: Any) -> Any:
        if args[-1] == "head":
            invocation[:] = [args, kwargs]
            args = [*args[:-1], "20261005_0076"]
        return original(args, **kwargs)

    harness = cast(Any, _postgres_harness).__wrapped__()
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", parent_first)
        engine = next(harness)

    async def populate() -> tuple[Any, UUID, Any]:
        setup = await _setup(engine, tmp_path)
        call, identifier = await direct_call(setup), uuid4()
        async with setup.sessions() as db, db.begin():
            await db.execute(
                text(
                    "INSERT INTO conversation_prospects (id, tenant_id, display_name, "
                    "created_by_person_id, owner_person_id, revision, created_at, updated_at) "
                    "VALUES (:id, :tenant, 'Legacy Fictional', :person, :person, 4, :now, :now)"
                ),
                {
                    "id": identifier,
                    "tenant": setup.state.tenant_id,
                    "person": setup.state.person_id,
                    "now": setup.clock[0],
                },
            )
            await db.execute(
                text(
                    "INSERT INTO conversation_prospect_memberships (id, tenant_id, prospect_id, "
                    "submission_id, linked_by_person_id, created_at) "
                    "VALUES (:id, :tenant, :prospect, :call, :person, :now)"
                ),
                {
                    "id": uuid4(),
                    "tenant": setup.state.tenant_id,
                    "prospect": identifier,
                    "call": call,
                    "person": setup.state.person_id,
                    "now": setup.clock[0],
                },
            )
            await store(setup, db)._audit(
                setup.state.actor, identifier, "created", {}, setup.clock[0]
            )
        async with setup.sessions() as db:
            row = (
                (
                    await db.execute(
                        text("SELECT * FROM conversation_prospects WHERE id=:id"),
                        {"id": identifier},
                    )
                )
                .mappings()
                .one()
            )
            events = (await db.scalars(select(AuditEvent))).all()
            members = (
                await db.execute(
                    select(
                        ConversationProspectMembership.id,
                        ConversationProspectMembership.submission_id,
                    )
                )
            ).all()
            preserved = (
                dict(row),
                [(e.id, e.event_hash) for e in events],
                [(m.id, m.submission_id) for m in members],
            )
        await setup.engine.dispose()
        return setup, identifier, preserved

    try:
        setup, identifier, preserved = run(populate())
        if not invocation:
            pytest.fail("The isolated parent migration was not captured.", pytrace=False)
        migrated = original([*invocation[0][:-1], "20261007_0077"], **invocation[1])
        if migrated.returncode:
            pytest.fail(
                "Isolated tags migration failed; environment/output withheld.", pytrace=False
            )
        with engine.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261007_0077"
            row = dict(
                db.execute(
                    text("SELECT * FROM conversation_prospects WHERE id=:id"), {"id": identifier}
                )
                .mappings()
                .one()
            )
            assert row.pop("tags") == [] and row == preserved[0]
            assert list(db.execute(select(AuditEvent.id, AuditEvent.event_hash))) == preserved[1]
            assert (
                list(
                    db.execute(
                        select(
                            ConversationProspectMembership.id,
                            ConversationProspectMembership.submission_id,
                        )
                    )
                )
                == preserved[2]
            )
        migrated = original(invocation[0], **invocation[1])
        if migrated.returncode:
            pytest.fail(
                "Isolated head migration failed; environment/output withheld.", pytrace=False
            )
        with engine.connect() as db:
            assert compare_metadata(MigrationContext.configure(db), model_metadata()) == []
    finally:
        harness.close()
