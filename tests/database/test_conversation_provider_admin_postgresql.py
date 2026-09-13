"""Disposable-loopback PostgreSQL proof for provider-admin configuration persistence.

This suite uses only the approved 127.0.0.1:55436 harness imported from the existing
conversation proof. It never contacts a provider, reads secrets, or enables paid work.
"""

from __future__ import annotations

from collections.abc import Coroutine, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
)
from ac_platform.conversation_intelligence.models import (
    ConversationCommand,
    ConversationProviderConfiguration,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.provider_registry import (
    ProviderConfig,
    RegistryConfig,
    RegistryPolicy,
    RouteConfig,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Any]:
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


@dataclass(frozen=True)
class AdminFixture:
    now: datetime
    tenant_id: UUID
    person_id: UUID
    session_id: UUID
    actor: ActorContext


async def seed_actor(
    engine: AsyncEngine,
    *,
    email: str = "admin@authorityclosers.com",
    role: str = "owner",
    verified: bool = True,
    permissions: frozenset[str] = frozenset({"admin_surface"}),
) -> AdminFixture:
    now = datetime.now(UTC)
    tenant_id, session_id = uuid4(), uuid4()
    async with AsyncSession(engine) as database, database.begin():
        database.add(
            Tenant(
                id=tenant_id,
                slug=tenant_id.hex,
                name="Disposable provider-admin tenant",
            )
        )
        person = await database.scalar(select(Person).where(Person.email == email))
        if person is None:
            person = Person(
                id=uuid4(),
                email=email,
                email_verified_at=now if verified else None,
            )
            database.add(person)
        else:
            person.email_verified_at = now if verified else None
        await database.flush()
        person_id = person.id
        database.add(Membership(tenant_id=tenant_id, person_id=person_id, role=role))
        await database.flush()
        database.add(
            IdentitySession(
                id=session_id,
                person_id=person_id,
                selected_tenant_id=tenant_id,
                token_hash=session_id.bytes * 2,
                expires_at=now + timedelta(days=1),
            )
        )
    return AdminFixture(
        now,
        tenant_id,
        person_id,
        session_id,
        ActorContext(person_id, session_id, tenant_id, permissions),
    )


def app(database: AsyncSession, fixture: AdminFixture) -> ConversationProviderAdmin:
    return ConversationProviderAdmin(ConversationApplication(database, clock=lambda: fixture.now))


def run_async(coroutine: Coroutine[Any, Any, Any]) -> Any:
    return run(coroutine)


def empty_config(revision: str = "admin-config-v1") -> dict[str, Any]:
    return RegistryConfig(
        revision=revision,
        policy=RegistryPolicy(),
        providers=(),
        routes=(),
    ).as_dict()


def dormant_config(
    *, revision: str = "admin-dormant-v1", max_cost_paise: int | None = None
) -> dict[str, Any]:
    provider = ProviderConfig(
        provider_id="ollama",
        model_id="admin-registered-model",
        endpoint=None,
        endpoint_sha256=None,
        credential_ref=None,
        provider_terms_ref=None,
        privacy_ref=None,
        pricing_ref=None,
        free_allowance_ref=None,
        permission_ref=None,
        endpoint_approval_ref=None,
        local_endpoint_approval_ref=None,
        max_cost_paise=max_cost_paise,
    )
    route = RouteConfig(
        task="coaching",
        provider_id="ollama",
        model_id="admin-registered-model",
        recipe_revision="admin-recipe-v1",
        profile_revision="admin-profile-v1",
        prompt_revision="admin-prompt-v1",
        required_input_stage="C4",
        reuses_checkpoint_stage="C2",
    )
    return RegistryConfig(
        revision=revision,
        policy=RegistryPolicy(),
        providers=(provider,),
        routes=(route,),
    ).as_dict()


def paid_config() -> dict[str, Any]:
    config = empty_config("paid-config-v1")
    config["policy"] = RegistryPolicy(
        allow_paid=True,
        paid_approval_ref="ref:approval:paid-test",
    ).as_dict()
    return config


@pytest.mark.parametrize(
    "email",
    ["admin@authorityclosers.com", "dipak@authorityclosers.com", "suyash@authorityclosers.com"],
)
def test_verified_control_account_can_save_replay_and_append_revisions(
    postgres_harness: Any,
    email: str,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            fixture = await seed_actor(engine, role="owner", email=email)
            configuration = empty_config()
            async with AsyncSession(engine) as database, database.begin():
                service = app(database, fixture)
                first = await service.save(
                    fixture.actor,
                    configuration,
                    expected_revision=0,
                    key="provider-config-first",
                )
                assert first["revision"] == 1
                assert first["execution_activated"] is False
                assert first["configuration"] == configuration
                replay = await service.save(
                    fixture.actor,
                    configuration,
                    expected_revision=0,
                    key="provider-config-first",
                )
                assert replay == first
                with pytest.raises(ConversationConflict):
                    await service.save(
                        fixture.actor,
                        empty_config("different-config-v1"),
                        expected_revision=0,
                        key="provider-config-first",
                    )
                with pytest.raises(ConversationConflict):
                    await service.save(
                        fixture.actor,
                        empty_config("stale-config-v1"),
                        expected_revision=0,
                        key="provider-config-stale",
                    )
                second = await service.save(
                    fixture.actor,
                    empty_config("admin-config-v2"),
                    expected_revision=1,
                    key="provider-config-second",
                )
                assert second["revision"] == 2
                assert second["configuration"] != first["configuration"]
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationProviderConfiguration)
                        .where(ConversationProviderConfiguration.tenant_id == fixture.tenant_id)
                    )
                    == 2
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationCommand)
                        .where(
                            ConversationCommand.tenant_id == fixture.tenant_id,
                            ConversationCommand.action == "provider_configuration",
                        )
                    )
                    == 2
                )
        finally:
            await engine.dispose()

    run_async(exercise())


@pytest.mark.parametrize(
    ("email", "role", "verified", "permissions"),
    [
        ("wrong@authorityclosers.com", "owner", True, frozenset({"admin_surface"})),
        ("dipak@authorityclosers.com", "owner", False, frozenset({"admin_surface"})),
        ("suyash@authorityclosers.com", "learner", True, frozenset({"admin_surface"})),
        ("admin@authorityclosers.com", "learner", True, frozenset({"admin_surface"})),
        ("admin@authorityclosers.com", "owner", False, frozenset({"admin_surface"})),
        ("admin@authorityclosers.com", "owner", True, frozenset()),
    ],
)
def test_non_control_or_non_admin_actor_cannot_save(
    postgres_harness: Any,
    email: str,
    role: str,
    verified: bool,
    permissions: frozenset[str],
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            fixture = await seed_actor(
                engine,
                email=email,
                role=role,
                verified=verified,
                permissions=permissions,
            )
            async with AsyncSession(engine) as database, database.begin():
                with pytest.raises(ConversationDenied):
                    await app(database, fixture).save(
                        fixture.actor,
                        empty_config(),
                        expected_revision=0,
                        key="denied-provider-config",
                    )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationProviderConfiguration)
                        .where(ConversationProviderConfiguration.tenant_id == fixture.tenant_id)
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    run_async(exercise())


def test_admin_role_is_allowed_but_paid_configuration_is_rejected(
    postgres_harness: Any,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            fixture = await seed_actor(engine, role="admin")
            async with AsyncSession(engine) as database, database.begin():
                service = app(database, fixture)
                with pytest.raises(ConversationDenied, match="zero paid spend"):
                    await service.save(
                        fixture.actor,
                        paid_config(),
                        expected_revision=0,
                        key="paid-provider-config",
                    )
                with pytest.raises(ConversationDenied, match="zero paid spend"):
                    await service.save(
                        fixture.actor,
                        dormant_config(max_cost_paise=1),
                        expected_revision=0,
                        key="costed-provider-config",
                    )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationProviderConfiguration)
                        .where(ConversationProviderConfiguration.tenant_id == fixture.tenant_id)
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    run_async(exercise())


def test_raw_secret_value_is_rejected_and_never_stored(postgres_harness: Any) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        secret = "sk_" + "a" * 25
        try:
            fixture = await seed_actor(engine)
            configuration = dormant_config()
            configuration["providers"][0]["credential_ref"] = secret
            async with AsyncSession(engine) as database, database.begin():
                with pytest.raises(ConversationError) as caught:
                    await app(database, fixture).save(
                        fixture.actor,
                        configuration,
                        expected_revision=0,
                        key="secret-provider-config",
                    )
                assert secret not in str(caught.value)
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationProviderConfiguration)
                        .where(ConversationProviderConfiguration.tenant_id == fixture.tenant_id)
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    run_async(exercise())


def test_provider_configuration_rows_are_append_only(postgres_harness: Any) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            fixture = await seed_actor(engine)
            async with AsyncSession(engine) as database, database.begin():
                saved = await app(database, fixture).save(
                    fixture.actor,
                    dormant_config(),
                    expected_revision=0,
                    key="append-only-provider-config",
                )
                row_id = UUID(saved["id"])
            async with AsyncSession(engine) as database:
                with pytest.raises(DBAPIError):
                    async with database.begin():
                        await database.execute(
                            update(ConversationProviderConfiguration)
                            .where(ConversationProviderConfiguration.id == row_id)
                            .values(revision=99)
                        )
            async with AsyncSession(engine) as database:
                with pytest.raises(DBAPIError):
                    async with database.begin():
                        await database.execute(
                            delete(ConversationProviderConfiguration).where(
                                ConversationProviderConfiguration.id == row_id
                            )
                        )
            async with AsyncSession(engine) as database, database.begin():
                row = await database.get(ConversationProviderConfiguration, row_id)
                assert row is not None and row.revision == 1
        finally:
            await engine.dispose()

    run_async(exercise())
