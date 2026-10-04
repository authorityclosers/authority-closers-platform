"""Isolated migrated loopback PostgreSQL; fictional fixtures and no provider HTTP."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository, verify_audit_chain_sync
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import CapabilityGrant, CapabilityRevocation
from ac_platform.authorization.platform import platform_projection
from ac_platform.billing.application import BillingApplication
from ac_platform.billing.catalogue import StaticCatalogue
from ac_platform.billing.checkout import CheckoutService
from ac_platform.billing.ledger import BillingLedger
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.billing.order_models import (
    BillingOrder,
    BillingOrderEvent,
    BillingPaymentEvent,
    BillingPeriod,
    BillingProviderSettings,
    BillingRefundEvent,
    BillingSubscription,
)
from ac_platform.billing.projection import Use
from ac_platform.development import billing_qa_fixture as fixture
from ac_platform.http.auth import install_identity_http
from ac_platform.http.billing import install_billing_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import EmailChallenge, Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.password_auth import PasswordAuthError
from ac_platform.outbox.models import OutboxEvent
from ac_platform.payments.fake import FakePaymentProvider
from ac_platform.payments.registry import PaymentProviderRegistry
from ac_platform.plans.models import Plan
from ac_platform.staff_billing.read import billing_overview
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_password_identity_http_postgresql import (
    _email_code_settings,
    _run_async,
)
from tests.integration.test_password_identity_http_postgresql import (
    postgres_harness as _postgres_harness,
)


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def test_preview_apply_replay_refusals_sign_in_and_canonical_staff_refund(
    postgres_harness, monkeypatch
):
    async def exercise():
        public, operations, manager = uuid4(), uuid4(), uuid4()
        original_learner = uuid4()
        settings = _email_code_settings(
            postgres_harness.schema_url,
            public_tenant_id=public,
            operations_tenant_id=operations,
            consent_version="fictional-billing-consent-v1",
        ).model_copy(
            update={"billing_fake_provider_signing_key": SecretStr("fictional-signing-key")}
        )
        engine = create_async_engine(postgres_harness.schema_url, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        password_values = {
            variable: "fictional-qa-fixture-password"
            for variable in fixture.PASSWORD_VARIABLES.values()
        }
        recorded = fixture.Authority(fixture.OWNER, uuid4(), uuid4(), uuid4(), uuid4())

        async with sessions() as database, database.begin():
            database.add_all(
                [
                    Tenant(id=public, slug=public.hex, name="Fictional Public"),
                    Tenant(id=operations, slug=operations.hex, name="Fictional Ops"),
                    Person(
                        id=manager,
                        email="fictional-manager@example.test",
                        email_verified_at=datetime.now(UTC),
                    ),
                    Person(
                        id=original_learner,
                        email="qa-learner-aut417@example.test",
                        first_name="Preserved fictional learner",
                    ),
                ]
            )
            await database.flush()
            database.add(
                Membership(tenant_id=operations, person_id=manager, role="owner", status="active")
            )
            await database.flush()

        def snapshot():
            with Session(postgres_harness.engine) as database:
                return tuple(
                    database.scalar(select(func.count()).select_from(model))
                    for model in (
                        Person,
                        Membership,
                        EmailChallenge,
                        IdentitySession,
                        CapabilityGrant,
                        CapabilityRevocation,
                        AuditEvent,
                        BillingAccount,
                        BillingOrder,
                        BillingSubscription,
                        BillingPeriod,
                        BillingPaymentEvent,
                        BillingLedgerEntry,
                        BillingOrderEvent,
                        BillingRefundEvent,
                        BillingProviderSettings,
                        OutboxEvent,
                    )
                ) + tuple(
                    (p.id, p.revision, p.monthly_price_paise, p.status)
                    for p in database.scalars(select(Plan).order_by(Plan.key))
                )

        async def revoke_for_test(database, grant_id):
            command_id = uuid4()
            reason = "Fictional revoked fixture"
            audit = await AuditRepository(database).append(
                event_id=uuid4(),
                tenant_id=operations,
                actor_type="operator_data_change",
                actor_person_id=None,
                action="authorization.capability_revoked",
                resource_type="capability_grant",
                resource_id=grant_id,
                payload={"command_id": str(command_id), "grant_id": str(grant_id)},
                reason=reason,
            )
            database.add(
                CapabilityRevocation(
                    id=command_id,
                    grant_id=grant_id,
                    revoked_by_person_id=manager,
                    audit_event_id=audit.id,
                    reason=reason,
                )
            )
            await database.flush()

        # The CLI's exact dev target guard still runs. Only its connector is
        # redirected to the disposable test schema, never the development DB.
        dev_settings = settings.model_copy(
            update={
                "environment": "development",
                "database_url": "postgresql+psycopg://ac_runtime@acdev-postgres/ac_platform",
            }
        )
        monkeypatch.setattr(
            fixture,
            "create_async_engine",
            lambda *a, **kw: create_async_engine(postgres_harness.schema_url, **kw),
        )
        monkeypatch.setattr(
            httpx.AsyncClient, "send", lambda *a, **k: pytest.fail("Provider HTTP attempted")
        )
        before = snapshot()
        try:
            with pytest.raises(fixture.FixtureRefused, match="unrevoked platform access manager"):
                await fixture.initialize(dev_settings, password_values)
            assert snapshot() == before
            async with sessions() as database, database.begin():
                manager_grant = await CapabilityApplication(
                    database, operations_tenant_id=operations
                ).bootstrap_first_manager(
                    person_id=manager, command_id=uuid4(), reason="Fictional test authority"
                )
            before = snapshot()
            with pytest.raises(fixture.FixtureRefused, match="unrevoked platform access manager"):
                async with sessions() as database, database.begin():
                    await revoke_for_test(database, manager_grant.id)
                    await fixture.seed(
                        database,
                        dev_settings,
                        password_values,
                        authority=recorded,
                        now=datetime.now(UTC),
                    )
            assert snapshot() == before
            preview = await fixture.initialize(dev_settings, password_values)
            assert preview["applied"] is False and preview["after"]["unused_minutes"] == 30
            assert snapshot() == before

            for bad_provider, mode in (("razorpay", "test"), ("fake", "live")):
                with pytest.raises(ValueError, match="Remote/live"):
                    async with sessions() as database, database.begin():
                        database.add(
                            BillingProviderSettings(
                                id=uuid4(),
                                revision=1,
                                provider=bad_provider,
                                mode=mode,
                                enabled=False,
                                plan_refs={},
                                reason="Fictional unsafe history",
                                created_at=datetime.now(UTC),
                            )
                        )
                        await database.flush()
                        await fixture.seed(
                            database,
                            settings,
                            password_values,
                            authority=recorded,
                            now=datetime.now(UTC),
                        )
                assert snapshot() == before
            with pytest.raises(ValueError, match="without provenance"):
                async with sessions() as database, database.begin():
                    database.add(Person(id=uuid4(), email=fixture.EMAILS["staff"]))
                    await database.flush()
                    await fixture.seed(
                        database,
                        settings,
                        password_values,
                        authority=recorded,
                        now=datetime.now(UTC),
                    )
            assert snapshot() == before

            result = await fixture.initialize(
                dev_settings, password_values, apply=True, authority=recorded
            )
            after = result["after"]
            assert after["provider"] == "fake" and after["mode"] == "test"
            assert after["unused_minutes"] == 30 and after["kind"] == "subscription.charged"
            with Session(postgres_harness.engine) as database:
                grant = database.get(CapabilityGrant, fixture.GRANT_ID)
                assert grant.permission == "platform_billing_manage"
                assert grant.granted_by_person_id == UUID(after["staff_person_id"])
                grant_audit = database.get(AuditEvent, grant.audit_event_id)
                seed_audit = database.get(AuditEvent, fixture.AUDIT_ID)
                for audit, command_id in (
                    (grant_audit, fixture.GRANT_ID),
                    (seed_audit, fixture.AUDIT_ID),
                ):
                    assert audit.actor_type == "operator_data_change"
                    assert audit.actor_person_id is None and audit.session_id is None
                    assert audit.payload["approver"] == recorded.approver
                    assert audit.payload["issue"] == fixture.ISSUE
                    assert audit.payload["environment"] == "development"
                    assert audit.payload["command_id"] == str(command_id)
                assert (
                    database.scalar(
                        select(func.count())
                        .select_from(IdentitySession)
                        .where(IdentitySession.person_id == manager)
                    )
                    == 0
                )
                customer_sessions = list(database.scalars(select(IdentitySession)))
                assert len(customer_sessions) == 1
                assert customer_sessions[0].person_id == UUID(after["owner_person_id"])
                assert customer_sessions[0].revoked_at is not None
            applied = snapshot()
            replay = await fixture.initialize(
                dev_settings, password_values, apply=True, authority=recorded
            )
            assert replay["replayed"] and replay["before"] == replay["after"] == after
            assert snapshot() == applied
            for environ, moment, match in (
                (
                    password_values
                    | {fixture.PASSWORD_VARIABLES["staff"]: "fictional-wrong-password"},
                    datetime.now(UTC),
                    "email or password",
                ),
                (
                    password_values,
                    datetime.fromisoformat(after["verified_at"]) + timedelta(days=8),
                    "refusing refresh",
                ),
            ):
                with pytest.raises((ValueError, PasswordAuthError), match=match):
                    async with sessions() as database, database.begin():
                        await fixture.seed(
                            database, settings, environ, authority=recorded, now=moment
                        )
                assert snapshot() == applied
            with pytest.raises(ValueError, match="capability differs"):
                async with sessions() as database, database.begin():
                    await revoke_for_test(database, fixture.GRANT_ID)
                    await fixture.seed(
                        database,
                        settings,
                        password_values,
                        authority=recorded,
                        now=datetime.now(UTC),
                    )
            assert snapshot() == applied
            with pytest.raises(ValueError, match="refusing refresh"):
                async with sessions() as database, database.begin():
                    order = await database.get(BillingOrder, UUID(after["order_id"]))
                    ledger = CheckoutService(
                        catalogue=StaticCatalogue(),
                        providers=PaymentProviderRegistry([]),
                        public_learner_tenant_id=public,
                        operations_tenant_id=operations,
                        return_url_base="https://example.test",
                    ).ledger(database)
                    lot = (await ledger.entries(order.account_id))[0]
                    await ledger.write_closing(
                        lot=lot,
                        kind="correction",
                        seconds=60,
                        remainder=1800,
                        source_ref="fictional-test-closing",
                        actor_type="system",
                        reason="Fictional changed fixture",
                    )
                    await fixture.seed(
                        database,
                        settings,
                        password_values,
                        authority=recorded,
                        now=datetime.now(UTC),
                    )
            assert snapshot() == applied

            # Trial-only usage keeps the paid lot refundable; usage spilling
            # into the paid lot refuses, using the canonical ledger projection.
            for seconds, refused in ((60, False), (3601, True)):
                with monkeypatch.context() as patch:

                    async def uses(*args, seconds=seconds, refused=refused, **kwargs):
                        return [
                            Use(
                                "fictional-use",
                                datetime.fromisoformat(after["verified_at"])
                                - timedelta(seconds=0 if refused else 1),
                                seconds,
                            )
                        ]

                    patch.setattr(BillingLedger, "person_uses", uses)
                    async with sessions() as database:
                        transaction = await database.begin()
                        try:
                            if refused:
                                with pytest.raises(ValueError, match="refusing refresh"):
                                    await fixture.seed(
                                        database,
                                        settings,
                                        password_values,
                                        authority=recorded,
                                        now=datetime.now(UTC),
                                    )
                            else:
                                assert (
                                    await fixture.seed(
                                        database,
                                        settings,
                                        password_values,
                                        authority=recorded,
                                        now=datetime.now(UTC),
                                    )
                                )["after"]["unused_minutes"] == 30
                        finally:
                            await transaction.rollback()
                assert snapshot() == applied

            # Sign in through the normal password surface and prove the canonical
            # staff action works without enabling/switching a database provider.
            monkeypatch.undo()
            app = FastAPI()
            register_problem_handlers(app)
            require_actor = install_identity_http(app, settings=settings, sessions=sessions)
            service = CheckoutService(
                catalogue=StaticCatalogue(),
                providers=PaymentProviderRegistry(
                    [FakePaymentProvider(signing_key="fictional-signing-key")]
                ),
                public_learner_tenant_id=public,
                operations_tenant_id=operations,
                return_url_base="https://example.test",
            )
            install_billing_http(
                app,
                settings=settings,
                require_actor=require_actor,
                commands=BillingApplication(service),
            )
            origin = str(settings.admin_app_url).rstrip("/")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=origin, headers={"Origin": origin}
            ) as browser:
                login = await browser.post(
                    "/v1/auth/password/login",
                    json={
                        "email": fixture.EMAILS["staff"],
                        "password": password_values[fixture.PASSWORD_VARIABLES["staff"]],
                    },
                )
                assert login.status_code == 200
                assert login.json()["person_id"] == after["staff_person_id"]
                async with sessions() as database, database.begin():
                    actor = (
                        await AsyncIdentityApplication(
                            database, token_pepper=settings.session_token_pepper.get_secret_value()
                        ).resolve_actor_read_only(browser.cookies.get(settings.session_cookie_name))
                    ).actor
                    assert "platform_billing_manage" in await platform_projection(
                        database, actor, operations_tenant_id=operations
                    )
                    overview = await billing_overview(database, now=datetime.now(UTC))
                    payment = next(
                        p for p in overview.payments if p.payment_id == after["payment_id"]
                    )
                    assert (
                        payment.refund_state == "available"
                        and payment.customer.email == fixture.EMAILS["customer"]
                    )
                refund = await browser.post(
                    f"/v1/platform/billing/payments/{after['payment_id']}/refund",
                    headers={"Idempotency-Key": "fictional-qa-refund"},
                    json={"reason": "Fictional QA proof only"},
                )
                assert refund.status_code == 202 and refund.json()["refund"]["state"] == "pending"
            async with sessions() as database, database.begin():
                overview = await billing_overview(database, now=datetime.now(UTC))
                assert (
                    next(
                        p for p in overview.payments if p.payment_id == after["payment_id"]
                    ).refund_state
                    == "refunded"
                )
            with pytest.raises(ValueError, match="refusing refresh"):
                async with sessions() as database, database.begin():
                    await fixture.seed(
                        database,
                        settings,
                        password_values,
                        authority=recorded,
                        now=datetime.now(UTC),
                    )
            with Session(postgres_harness.engine) as database:
                assert (
                    database.scalar(select(func.count()).select_from(BillingProviderSettings)) == 0
                )
                assert (
                    database.get(Person, original_learner).first_name
                    == "Preserved fictional learner"
                )
                assert verify_audit_chain_sync(database, operations).valid
            print(
                "Fictional isolated PostgreSQL readback: "
                + json.dumps(after, default=str, sort_keys=True)
            )
        finally:
            await engine.dispose()

    _run_async(exercise())
