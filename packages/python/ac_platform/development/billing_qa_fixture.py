"""AUT-969 dev-only billing QA fixture; preview by default, never a HTTP route.

Root must verify the recorded owner authorities before applying the released
command. Reference arguments record that authority; they do not confer it.
Credentials enter through Infisical's dev /application environment only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Never
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import CapabilityGrant, CapabilityRevocation
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.billing.catalogue import PlanCopy, StaticCatalogue
from ac_platform.billing.checkout import CheckoutService, ProviderChoice
from ac_platform.billing.commands import Caller, CheckoutCommand
from ac_platform.billing.models import BillingAccount
from ac_platform.billing.order_models import (
    BillingOrder,
    BillingProviderSettings,
)
from ac_platform.billing.projection import payment_refundable
from ac_platform.billing.settlement import Settlement
from ac_platform.billing.simulation import FakeCheckout
from ac_platform.conversation_intelligence.admission_lock import take_admission_lock
from ac_platform.development.seed import verify_registration_without_mail
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person
from ac_platform.identity.password_auth import PasswordIdentityService, validate_password
from ac_platform.payments.fake import FakePaymentProvider
from ac_platform.payments.ports import Money
from ac_platform.payments.recurring import BillingInterval, RecurringPlan
from ac_platform.payments.registry import PaymentProviderRegistry
from ac_platform.tenancy.learner_provisioning import AsyncLearnerProvisioningApplication
from ac_platform.tenancy.models import Membership

ISSUE = "AUT-969"
SEED = "aut969-billing-qa-v1"
OWNER = "ZyTZxLQfn8zFPFVZ5OjwisIX96Xmo4j0"
NAMESPACE = UUID("84ae8f38-a905-4c7c-a85a-75a579264bc3")
AUDIT_ID, GRANT_ID = (uuid5(NAMESPACE, name) for name in ("seed", "staff-grant"))
EMAILS = {kind: f"qa-billing-{kind}-aut969@example.test" for kind in ("staff", "customer")}
PASSWORD_VARIABLES = {kind: f"AC_DEV_BILLING_FIXTURE_PASSWORD_{kind.upper()}" for kind in EMAILS}
TOKEN_VARIABLE = "AC_DEV_BILLING_FIXTURE_OPERATOR_SESSION_TOKEN"  # noqa: S105
REASON = f"{ISSUE}: fictional development billing QA only"
PLAN = PlanCopy("personal", "AUT-969 fictional QA", 1, "active", 100, None, 30, 1, 1, False, 30, 0)


class FixtureRefused(ValueError):
    """Only controlled, credential-free messages may be shown to an operator."""


@dataclass(frozen=True)
class Authority:
    approver: str
    data_approval: UUID
    secrets_approval: UUID
    billing_approval: UUID
    run_id: UUID


def require_target(settings: Settings, environ: Mapping[str, str]) -> None:
    url = make_url(settings.database_url)
    if (
        settings.environment != "development"
        or url.drivername != "postgresql+psycopg"
        or (url.host, url.port or 5432, url.database, url.username)
        != ("acdev-postgres", 5432, "ac_platform", "ac_runtime")
        or url.query
        or any(name.upper().startswith("PG") for name in environ)
        or settings.billing_allow_live
        or any(
            (
                settings.razorpay_key_id,
                settings.razorpay_key_secret,
                settings.razorpay_webhook_secret,
            )
        )
    ):
        raise FixtureRefused(
            "Only the exact development database and offline fake provider are allowed."
        )


class FixtureCheckout(CheckoutService):
    """Process-local routing/catalogue: never persist or enable provider settings."""

    async def provider_choice(self, database: AsyncSession) -> ProviderChoice:
        return ProviderChoice(
            self.providers.get("fake"),
            BillingProviderSettings(provider="fake", mode="test", enabled=True, plan_refs={}),
        )

    async def provider_plan_ref(
        self,
        database: AsyncSession,
        choice: ProviderChoice,
        plan: PlanCopy,
        interval: str,
        money: Money,
    ) -> str:
        provider = choice.provider
        assert type(provider) is FakePaymentProvider and interval == "month"
        return await provider.create_plan(
            RecurringPlan(SEED.replace("-", "_"), PLAN.name, money, BillingInterval.MONTHLY)
        )


async def readback(
    database: AsyncSession, settings: Settings, service: CheckoutService, audit: AuditEvent
) -> dict[str, Any]:
    assert (
        settings.public_learner_tenant_id is not None and settings.operations_tenant_id is not None
    )
    people = {kind: UUID(value) for kind, value in audit.payload["people"].items()}
    if (
        set(people) != set(EMAILS)
        or audit.action != "development.billing_qa_fixture_created"
        or audit.payload.get("issue") != ISSUE
        or audit.payload.get("seed") != SEED
        or audit.resource_id != SEED
        or audit.tenant_id != settings.operations_tenant_id
    ):
        raise ValueError("Seed provenance differs; refusing repair.")
    for kind, person_id in people.items():
        person = await database.get(Person, person_id)
        if (
            person is None
            or person.email != EMAILS[kind]
            or person.status != "active"
            or person.email_verified_at is None
            or person.consent_version != settings.learner_consent_version
        ):
            raise ValueError("Fixture identity differs; refusing repair.")
    membership = await database.get(
        Membership, (settings.public_learner_tenant_id, people["customer"])
    )
    if (
        membership is None
        or membership.role != "learner"
        or membership.status != "active"
        or membership.ended_at is not None
    ):
        raise ValueError("Fixture membership differs; refusing repair.")
    grant = await database.get(CapabilityGrant, GRANT_ID)
    revoked = await database.scalar(
        select(CapabilityRevocation.id).where(CapabilityRevocation.grant_id == GRANT_ID)
    )
    if (
        grant is None
        or revoked
        or grant.subject_person_id != people["staff"]
        or grant.permission != "platform_billing_manage"
        or grant.scope_kind != "platform"
    ):
        raise ValueError("Fixture capability differs; refusing repair.")
    order = await database.get(BillingOrder, UUID(audit.payload["order_id"]))
    payment = await Settlement._verified_payment(database, audit.payload["payment_id"], "fake")
    account = None if order is None else await database.get(BillingAccount, order.account_id)
    if (
        order is None
        or payment is None
        or account is None
        or account.person_id != people["customer"]
        or account.tenant_id != settings.public_learner_tenant_id
        or payment.order_id != order.id
        or order.provider != "fake"
        or order.mode != "test"
        or order.plan_name != PLAN.name
        or order.minutes != PLAN.included_minutes
    ):
        raise ValueError("Fixture payment differs; refusing repair.")
    ledger = service.ledger(database)
    entries = await ledger.entries(account.id)
    lots = ledger.lots_from_entries(entries)
    sources = await Settlement._sources(database, order, payment)
    payment_lot_ids = {str(entry.id) for entry in entries if entry.source_ref in sources}
    payment_lots = [lot for lot in lots if lot.lot_id in payment_lot_ids]
    projection = (
        await ledger.project_person(
            tenant_id=account.tenant_id, person_id=people["customer"], now=service.clock()
        )
    ).projection
    if (
        not payment_refundable(projection, payment_lots, verified_at=payment.verified_at)
        or len(payment_lots) != 1
        or sum(lot.seconds for lot in payment_lots) != 1800
    ):
        raise ValueError("Fixture payment is no longer unused/refundable; refusing refresh.")
    return {
        "seed": SEED,
        "issue": ISSUE,
        "audit_id": str(audit.id),
        "staff_person_id": str(people["staff"]),
        "owner_person_id": str(people["customer"]),
        "order_id": str(order.id),
        "payment_id": payment.payment_ref,
        "provider": order.provider,
        "mode": order.mode,
        "kind": payment.kind,
        "verified_at": payment.verified_at.isoformat(),
        "unused_minutes": 30,
        "authority": audit.payload["authority"],
    }


async def seed(
    database: AsyncSession,
    settings: Settings,
    environ: Mapping[str, str],
    *,
    authority: Authority | None,
    now: datetime,
) -> dict[str, Any]:
    """Caller owns one transaction, rolling it back for previews and all refusals."""
    assert (
        settings.public_learner_tenant_id is not None and settings.operations_tenant_id is not None
    )
    capabilities = CapabilityApplication(
        database, operations_tenant_id=settings.operations_tenant_id
    )
    # Match the capability CLI's governance -> identity -> subject lock order.
    await capabilities._governance()
    identity = AsyncIdentityApplication(
        database, token_pepper=settings.session_token_pepper.get_secret_value()
    )
    actor = (await identity.resolve_actor_read_only(environ[TOKEN_VARIABLE])).actor
    await capabilities.require(
        actor.person_id, "platform_access_manage", CapabilityScope("platform")
    )
    await take_admission_lock(database, settings.public_learner_tenant_id)
    if await database.scalar(
        select(BillingProviderSettings.id).where(
            (BillingProviderSettings.provider != "fake") | (BillingProviderSettings.mode != "test")
        )
    ):
        raise ValueError("Remote/live provider history exists; refusing.")
    assert settings.billing_fake_provider_signing_key is not None
    fake = FakePaymentProvider(
        signing_key=settings.billing_fake_provider_signing_key.get_secret_value()
    )
    service = FixtureCheckout(
        catalogue=StaticCatalogue((PLAN,)),
        providers=PaymentProviderRegistry([fake]),
        public_learner_tenant_id=settings.public_learner_tenant_id,
        operations_tenant_id=settings.operations_tenant_id,
        return_url_base="https://salesxray-dev.authorityclosers.com",
        clock=lambda: now,
    )
    previous = await database.get(AuditEvent, AUDIT_ID)
    password_identity = PasswordIdentityService(
        database, token_secret=settings.email_challenge_secret.get_secret_value()
    )
    if previous is not None:
        after = await readback(database, settings, service, previous)
        for kind, email in EMAILS.items():
            await password_identity.authenticate(
                email=email, password=environ[PASSWORD_VARIABLES[kind]]
            )
        return {"before": after, "after": after, "replayed": True}
    if await database.scalar(
        select(Person.id).where(func.lower(Person.email).in_(EMAILS.values()))
    ):
        raise ValueError("Fixture email already exists without provenance; refusing overwrite.")
    people = {}
    for kind, email in EMAILS.items():
        registration = await password_identity.register(
            email=email,
            first_name=f"Fictional Billing QA {kind.title()}",
            whatsapp_number="+14155550169",
            password=environ[PASSWORD_VARIABLES[kind]],
            consent_version=settings.learner_consent_version or "",
        )
        person = await verify_registration_without_mail(
            database,
            password_identity,
            registration,
            secret=settings.email_challenge_secret.get_secret_value(),
        )
        people[kind] = person.id
    await AsyncLearnerProvisioningApplication(database).ensure(
        person_id=people["customer"],
        tenant_id=settings.public_learner_tenant_id,
        required_consent_version=settings.learner_consent_version or "",
    )
    await capabilities.grant(
        actor,
        command_id=GRANT_ID,
        subject_person_id=people["staff"],
        permission="platform_billing_manage",
        scope=CapabilityScope("platform"),
        reason=REASON,
    )
    command = CheckoutCommand(
        "subscription",
        "personal",
        "personal",
        SEED,
        service.digest(SEED),
        interval="month",
        seats=1,
    )
    customer_session = await identity.issue_authenticated_session(people["customer"])
    view = await service.checkout(
        database,
        Caller(
            people["customer"],
            customer_session.metadata.id,
            settings.public_learner_tenant_id,
            "learner",
        ),
        command,
    )
    order = await database.get(BillingOrder, UUID(view.order.order_id))
    assert order is not None
    service.clock = lambda: now + timedelta(microseconds=1)
    await FakeCheckout(service).submit(
        database, order.id, fake.checkout_token(order.order_ref), "pay"
    )
    await identity.revoke_self(customer_session.token, customer_session.metadata.id, reason=REASON)
    audit = await AuditRepository(database).append(
        event_id=AUDIT_ID,
        tenant_id=settings.operations_tenant_id,
        actor_person_id=actor.person_id,
        session_id=actor.session_id,
        action="development.billing_qa_fixture_created",
        resource_type="billing_qa_fixture",
        resource_id=SEED,
        payload={
            "issue": ISSUE,
            "seed": SEED,
            "people": {k: str(v) for k, v in people.items()},
            "order_id": str(order.id),
            "payment_id": f"fake_pay_{order.order_ref}",
            "authority": {k: str(v) for k, v in asdict(authority).items()}
            if authority
            else {"preview": True},
        },
        reason=REASON,
        now=now,
    )
    return {
        "before": {"seed_present": False},
        "after": await readback(database, settings, service, audit),
        "replayed": False,
    }


class _PreviewComplete(Exception):
    """Rollback the whole prospective fixture, including audit and identity rows."""


async def initialize(
    settings: Settings,
    environ: Mapping[str, str],
    *,
    apply: bool = False,
    authority: Authority | None = None,
) -> dict[str, Any]:
    require_target(settings, environ)
    if apply and (
        authority is None
        or authority.approver != OWNER
        or not all(
            isinstance(ref, UUID) and ref.int
            for ref in (
                authority.data_approval,
                authority.secrets_approval,
                authority.billing_approval,
                authority.run_id,
            )
        )
    ):
        raise FixtureRefused("Apply requires recorded owner data, secrets and billing authorities.")
    for variable in (*PASSWORD_VARIABLES.values(), TOKEN_VARIABLE):
        if not environ.get(variable):
            raise FixtureRefused(f"Missing {variable}.")
    for variable in PASSWORD_VARIABLES.values():
        validate_password(environ[variable])
    if settings.billing_fake_provider_signing_key is None:
        raise FixtureRefused("Missing AC_BILLING_FAKE_PROVIDER_SIGNING_KEY.")
    if (
        not settings.learner_consent_version
        or settings.public_learner_tenant_id is None
        or settings.operations_tenant_id is None
    ):
        raise FixtureRefused("Explicit public/operations tenants and consent version are required.")
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as database:
            try:
                async with database.begin():
                    result = await seed(
                        database, settings, environ, authority=authority, now=datetime.now(UTC)
                    )
                    if not apply:
                        raise _PreviewComplete
            except _PreviewComplete:
                pass
        return {"applied": apply, **result}
    finally:
        await engine.dispose()


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise FixtureRefused("Invalid arguments; use --help.")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approver", choices=(OWNER,))
    for name in ("data-approval", "secrets-approval", "billing-approval", "run-id"):
        parser.add_argument(f"--{name}", type=UUID)
    try:
        args = parser.parse_args(argv)
        authority = None
        if all(
            (
                args.approver,
                args.data_approval,
                args.secrets_approval,
                args.billing_approval,
                args.run_id,
            )
        ):
            authority = Authority(
                args.approver,
                args.data_approval,
                args.secrets_approval,
                args.billing_approval,
                args.run_id,
            )
        result = run_async(
            initialize(Settings(_env_file=None), os.environ, apply=args.apply, authority=authority)
        )
    except FixtureRefused as error:
        print(f"Billing QA fixture refused: {error}", file=sys.stderr)
        return 2
    except Exception:
        # Driver/settings/identity exceptions can contain secrets or SQL. Never echo them.
        print(
            "Billing QA fixture refused; check target, authority, secret names and fixture state.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
