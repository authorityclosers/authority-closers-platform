"""Fictional PostgreSQL receipts prove HTTP allowance parity and bounded owner reads."""

import json
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, select, update

from ac_platform.audit.service import AuditRepository
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.conversation_intelligence.acquisition_challenge import UploadChallenge
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.entitlements import MinuteGrant
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.minute_account_admin import (
    MINUTE_GRANT_ACTION,
    MINUTE_GRANT_RESOURCE_TYPE,
    append_minute_grant,
)
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.submission_labels import update_submission_label
from ac_platform.http.conversation_acquisition import install_acquisition_http
from ac_platform.http.conversation_acquisition_runtime import (
    AcquisitionRuntime,
    install_acquisition_runtime,
)
from tests.database.test_conversation_account_library_postgresql import (
    _seed_retained_guest_submission,
    _session,
)
from tests.database.test_conversation_acquisition_postgresql import source
from tests.database.test_conversation_postgresql import (
    application,
    run,
    seed,
    seed_budget,
    seed_run_intent,
)
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, PREFIX, _setup


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


async def _account_app(postgres_harness, tmp_path):
    setup = await _setup(postgres_harness, tmp_path)
    operations = await seed(setup.engine, role="owner")

    def factory(database):
        return AcquisitionSessions(
            database,
            tenant_id=setup.state.tenant_id,
            policy_revision="guest-processing-v1",
            operations_tenant_id=operations.tenant_id,
            clock=lambda: setup.clock[0],
        )

    setup.factory = factory
    install_acquisition_http(
        setup.app,
        settings=setup.settings,
        sessions=setup.sessions,
        require_actor=setup.require_actor,
        factory=factory,
        challenge=UploadChallenge(
            secret=setup.settings.session_token_pepper, hostname="salesxray.example.test"
        ),
    )
    return setup, operations


async def _read(client, statements, engine):
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await client.get("/v1/me/usage")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    return response.json()


def test_me_http_ledger_invariant_grants_labels_and_owner_isolation(
    postgres_harness, tmp_path, record_property
):
    async def exercise():
        setup, operations = await _account_app(postgres_harness, tmp_path)
        state = setup.state
        try:
            retained = await _seed_retained_guest_submission(setup)
            intent = await seed_run_intent(setup.engine, state, await seed_budget(setup.engine))
            async with setup.sessions() as db, db.begin():
                await application(db, state).request_run(state.actor, intent, key="older-upload")
                app = setup.factory(db)
                await app.claim(setup.guest.token, state.actor)
                await app.settle(retained["usage_id"], charged_seconds=1, receipt_sha256="a" * 64)
                for seconds, charged in ((30, 30), (20, 0), (40, None)):
                    usage_id = await app.reserve(source(seconds), actor=state.actor)
                    if charged is not None:
                        await app.settle(
                            usage_id,
                            charged_seconds=charged,
                            receipt_sha256=uuid4().hex * 2,
                            no_work=charged == 0,
                        )
                ownership = GuestOwnership(app)
                await update_submission_label(
                    ownership,
                    retained["submission_id"],
                    actor=state.actor,
                    expected_revision=0,
                    display_name="Older fictional name",
                )
                await update_submission_label(
                    ownership,
                    retained["submission_id"],
                    actor=state.actor,
                    expected_revision=1,
                    display_name="Fictional discovery call",
                )
                # The real grant helper and canonical audit event extend allowance once.
                grant_id, audit_id = uuid4(), uuid4()
                reason = "Fictional approved 10-minute add-on"
                await append_minute_grant(
                    db,
                    tenant_id=state.tenant_id,
                    person_id=state.person_id,
                    operations_tenant_id=operations.tenant_id,
                    grant=MinuteGrant(
                        str(state.tenant_id),
                        str(state.person_id),
                        str(grant_id),
                        600,
                        f"audit-event:{audit_id}",
                        str(operations.person_id),
                        reason,
                    ),
                )
                await AuditRepository(db).append(
                    event_id=audit_id,
                    tenant_id=operations.tenant_id,
                    actor_person_id=operations.person_id,
                    session_id=operations.session_id,
                    action=MINUTE_GRANT_ACTION,
                    resource_type=MINUTE_GRANT_RESOURCE_TYPE,
                    resource_id=grant_id,
                    reason=reason,
                    payload={
                        "idempotency_key": "fictional-10-minute-grant",
                        "request_digest": "b" * 64,
                        "grant_id": str(grant_id),
                        "tenant_id": str(state.tenant_id),
                        "person_id": str(state.person_id),
                        "minutes": 10,
                        "seconds": 600,
                    },
                )
            stranger = await seed(setup.engine, tenant_id=state.tenant_id)
            foreign = await seed(setup.engine)
            async with setup.sessions() as db, db.begin():
                await setup.factory(db).reserve(source(99), actor=stranger.actor)
                await setup.factory(db).reserve(source(88), token=setup.stranger.token)
                await AcquisitionSessions(
                    db, tenant_id=foreign.tenant_id, policy_revision="guest-processing-v1"
                ).reserve(source(77), actor=foreign.actor)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                usage = await _read(client, [], setup.engine)
                plan = (await client.get("/v1/me/plan")).json()
                session = (await client.get(PREFIX + "/session")).json()
                assert usage["allowance"] == plan["allowance"] == session["allowance"]
                record_property("me_plan_response", json.dumps(plan))
                record_property("me_usage_response", json.dumps(usage))
                assert usage["allowance"] == {
                    "allowance_seconds": 4200,
                    "committed_seconds": 191,
                    "available_seconds": 4009,
                }
                assert usage["earlier_seconds"] == 120 and usage["truncated"] is False
                assert sum(row["seconds"] for row in usage["calls"]) + 120 == 191
                assert len(usage["calls"]) == 4
                assert sorted((row["state"], row["seconds"]) for row in usage["calls"]) == [
                    ("charged", 1),
                    ("charged", 30),
                    ("not_charged", 0),
                    ("reserved", 40),
                ]
                labelled = next(
                    row
                    for row in usage["calls"]
                    if row["submission_id"] == str(retained["submission_id"])
                )
                assert labelled["display_name"] == "Fictional discovery call"
                library = (await client.get(PREFIX + "/submissions")).json()["submissions"]
                assert library[0]["display_name"] == labelled["display_name"]
                assert all(
                    row["display_name"] is None for row in usage["calls"] if row is not labelled
                )
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(ConversationPermission)
                        .where(
                            ConversationPermission.id
                            == select(ConversationRecording.permission_id)
                            .where(ConversationRecording.id == retained["recording_id"])
                            .scalar_subquery()
                        )
                        .values(retention_until=setup.clock[0] + timedelta(seconds=1))
                    )
                setup.clock[0] += timedelta(seconds=2)
                expired = await _read(client, [], setup.engine)
                assert expired["allowance"] == usage["allowance"]
                assert len(expired["calls"]) == 4
                assert all(row["display_name"] is None for row in expired["calls"])
                client.cookies.set(
                    setup.settings.session_cookie_name, await _session(setup, stranger)
                )
                other = (await client.get("/v1/me/usage")).json()
                assert [row["seconds"] for row in other["calls"]] == [99]
                assert other["earlier_seconds"] == 0
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_me_http_empty_and_101_rows_have_fixed_read_query_count(postgres_harness, tmp_path):
    async def exercise():
        setup, _ = await _account_app(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                statements = []
                empty = await _read(client, statements, setup.engine)
                assert empty == {
                    "allowance": {
                        "allowance_seconds": 3600,
                        "committed_seconds": 0,
                        "available_seconds": 3600,
                    },
                    "calls": [],
                    "earlier_seconds": 0,
                    "truncated": False,
                }
                query_count = len(statements)
                expected = []
                async with setup.sessions() as db, db.begin():
                    for _ in range(101):
                        setup.clock[0] += timedelta(seconds=1)
                        measured = source(1)
                        expected.append(str(measured.submission_id))
                        await setup.factory(db).reserve(measured, actor=setup.state.actor)
                statements.clear()
                usage = await _read(client, statements, setup.engine)
                assert len(statements) == query_count
                assert usage["truncated"] is True and len(usage["calls"]) == 100
                assert [row["submission_id"] for row in usage["calls"]] == expected[:0:-1]
                assert usage["allowance"]["committed_seconds"] == 101
                assert sum(row["seconds"] for row in usage["calls"]) == 100
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_runtime_new_account_reads_trial_before_any_billing_write(
    postgres_harness, tmp_path, record_property
):
    async def exercise():
        setup = await _setup(postgres_harness, tmp_path, gemini=True, separate_operations=True)
        try:
            assert setup.runtime.authority is not None
            assert (
                setup.runtime.authority.operations_tenant_id
                == setup.settings.operations_tenant_id
                != setup.state.tenant_id
            )
            assert setup.settings.sales_xray_trial_policy == "v1"
            assert setup.settings.sales_xray_trial_policy_switch_at is None
            assert setup.settings.billing_enabled is False
            install_acquisition_runtime(
                setup.app,
                settings=setup.settings,
                sessions=setup.sessions,
                require_actor=setup.require_actor,
                runtime=AcquisitionRuntime(
                    intake=setup.runtime,
                    challenge=UploadChallenge(
                        secret=setup.settings.session_token_pepper,
                        hostname="salesxray.example.test",
                    ),
                    preflight=NativeUploadPreflight(setup.native),
                    site_key="synthetic-site-key",
                    policy_revision="guest-processing-v1",
                ),
            )
            owned_accounts = select(BillingAccount.id).where(
                BillingAccount.tenant_id == setup.state.tenant_id,
                BillingAccount.person_id == setup.state.person_id,
            )
            owned_entries = select(BillingLedgerEntry.id).where(
                BillingLedgerEntry.account_id.in_(owned_accounts)
            )
            async with setup.sessions() as database:
                assert await database.scalar(owned_accounts.limit(1)) is None
                assert await database.scalar(owned_entries.limit(1)) is None
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                entry = await client.get(PREFIX + "/entry")
                assert entry.status_code == 200, entry.text
                assert entry.json()["allowance_seconds"] == 3600
                session = await client.get(PREFIX + "/session")
                assert session.status_code == 200, session.text
                expected = {
                    "allowance_seconds": 3600,
                    "committed_seconds": 0,
                    "available_seconds": 3600,
                }
                assert session.json() == {"state": "account", "allowance": expected}
                for path in ("/v1/me/plan", "/v1/me/usage"):
                    response = await client.get(path)
                    assert response.status_code == 200, response.text
                    assert response.json()["allowance"] == expected
                record_property("new_account_session", json.dumps(session.json()))
            async with setup.sessions() as database:
                assert await database.scalar(owned_accounts.limit(1)) is None
                assert await database.scalar(owned_entries.limit(1)) is None
        finally:
            await setup.engine.dispose()

    run(exercise())
