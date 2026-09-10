"""Real PostgreSQL coverage for academy-scoped community identity and leaderboard state."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import (
    CheckConstraint,
    UniqueConstraint,
    func,
    inspect,
    select,
    update,
)
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.community.application import (
    CommunityApplication,
    CommunityRevisionConflict,
    UsernameAlreadyClaimed,
    UsernameUnavailable,
    decode_cursor,
)
from ac_platform.community.models import AcademyPublicProfile, CommunityProfileMutationError
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.practice.application import POLICY_VERSION
from ac_platform.practice.models import (
    PracticeAttempt,
    PracticeLedgerEntry,
    PracticeParticipation,
    PracticeRewardClaim,
    PracticeSetVersion,
)
from ac_platform.tenancy.models import Membership, MembershipStatus, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import _run_async
from tests.integration.test_media_delivery_renewal_postgresql import (
    postgres_harness as postgres_harness,  # noqa: F401 - disposable migrated schema fixture
)
from tests.integration.test_studio_draft_authoring_postgresql import seed

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
BASE_DAY = date(2026, 9, 8)
WEEK_START = date(2026, 9, 7)


async def _event_count(database: AsyncSession, tenant_id: UUID, action: str) -> int:
    return int(
        await database.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id, AuditEvent.action == action)
        )
        or 0
    )


async def _add_person_and_membership(
    database: AsyncSession,
    *,
    tenant_id: UUID,
    email: str,
    role: str = "learner",
    membership_status: str = MembershipStatus.ACTIVE.value,
    person_status: str = PersonStatus.ACTIVE.value,
    email_verified: bool = True,
) -> ActorContext:
    person_id, session_id = uuid4(), uuid4()
    database.add(
        Person(
            id=person_id,
            email=email,
            status=person_status,
            email_verified_at=NOW if email_verified else None,
        )
    )
    database.add(
        Membership(
            tenant_id=tenant_id,
            person_id=person_id,
            role=role,
            status=membership_status,
            ended_at=NOW if membership_status == MembershipStatus.INACTIVE.value else None,
        )
    )
    await database.flush()
    database.add(
        IdentitySession(
            id=session_id,
            person_id=person_id,
            selected_tenant_id=tenant_id,
            token_hash=hashlib.sha256(session_id.bytes).digest(),
            created_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
    )
    await database.flush()
    return ActorContext(person_id=person_id, session_id=session_id, tenant_id=tenant_id)


async def _add_profile(
    database: AsyncSession,
    actor: ActorContext,
    username: str,
    *,
    opted_in: bool = True,
) -> None:
    assert actor.tenant_id is not None
    database.add(
        AcademyPublicProfile(
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            username=username,
            leaderboard_opted_in=opted_in,
            revision=1,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await database.flush()


async def _add_reward(
    database: AsyncSession,
    *,
    actor: ActorContext,
    set_version_id: UUID,
    audit_event_id: UUID,
    index: int,
    xp: int = 30,
    credits: int = 10,
    kind: str = "daily_set",
) -> None:
    assert actor.tenant_id is not None
    attempt_id, participation_id, claim_id = uuid4(), uuid4(), uuid4()
    local_day = BASE_DAY + timedelta(days=index)
    daily_slot = ((index % 2) + 1) if kind == "daily_set" else None
    database.add(
        PracticeAttempt(
            id=attempt_id,
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            set_version_id=set_version_id,
            revision=0,
            state="in_progress",
            issued_at=NOW,
            updated_at=NOW,
        )
    )
    await database.flush()
    database.add(
        PracticeParticipation(
            id=participation_id,
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            attempt_id=attempt_id,
            local_day=local_day,
            week_start=WEEK_START,
            timezone="Asia/Kolkata",
            policy_version=POLICY_VERSION,
            audit_event_id=audit_event_id,
            created_at=NOW,
        )
    )
    await database.flush()
    database.add(
        PracticeRewardClaim(
            id=claim_id,
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            participation_id=participation_id,
            kind=kind,
            dedup_key=f"community-fixture:{local_day}:{index}",
            credits=credits,
            xp=xp,
            daily_slot=daily_slot,
            local_day=local_day,
            week_start=WEEK_START,
            policy_version=POLICY_VERSION,
            audit_event_id=audit_event_id,
            created_at=NOW + timedelta(minutes=index),
        )
    )
    await database.flush()
    for unit, amount in (("credits", credits), ("xp", xp)):
        if amount:
            database.add_all(
                [
                    PracticeLedgerEntry(
                        id=uuid4(),
                        tenant_id=actor.tenant_id,
                        person_id=actor.person_id,
                        claim_id=claim_id,
                        unit=unit,
                        account="issuance",
                        amount=-amount,
                        created_at=NOW,
                    ),
                    PracticeLedgerEntry(
                        id=uuid4(),
                        tenant_id=actor.tenant_id,
                        person_id=actor.person_id,
                        claim_id=claim_id,
                        unit=unit,
                        account="available",
                        amount=amount,
                        created_at=NOW,
                    ),
                ]
            )
    await database.flush()


def test_concurrent_normalized_username_claims_have_one_owner(postgres_harness) -> None:  # noqa: F811
    async def run() -> None:
        engine = create_async_engine(
            postgres_harness.schema_url, pool_size=4, max_overflow=0, hide_parameters=True
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)

            async def claim(actor: ActorContext) -> dict[str, Any]:
                async with sessions() as database, database.begin():
                    return await CommunityApplication(database).claim_username(
                        actor, "  Shared_Name  "
                    )

            results = await asyncio.wait_for(
                asyncio.gather(*(claim(actor) for actor in state.actors), return_exceptions=True),
                timeout=10,
            )
            successes = [result for result in results if not isinstance(result, BaseException)]
            failures = [result for result in results if isinstance(result, BaseException)]
            assert len(successes) == 1
            assert len(failures) == 1
            assert isinstance(failures[0], UsernameUnavailable)
            assert successes[0]["username"] == "shared_name"

            async with sessions() as database:
                profiles = list(
                    await database.scalars(
                        select(AcademyPublicProfile).where(
                            AcademyPublicProfile.tenant_id == state.tenant_id
                        )
                    )
                )
                owner = next(
                    actor
                    for actor, result in zip(state.actors, results, strict=True)
                    if not isinstance(result, BaseException)
                )
                assert [(row.person_id, row.username) for row in profiles] == [
                    (owner.person_id, "shared_name")
                ]
                assert (
                    await _event_count(database, state.tenant_id, "community.username_claimed") == 1
                )
                assert (
                    await database.run_sync(
                        lambda sync: verify_audit_chain_sync(sync, state.tenant_id)
                    )
                ).valid
        finally:
            await engine.dispose()

    _run_async(run())


def test_same_person_username_retry_is_idempotent_and_audited_once(postgres_harness) -> None:  # noqa: F811
    async def run() -> None:
        engine = create_async_engine(postgres_harness.schema_url, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)
            actor = state.actors[0]
            async with sessions() as database, database.begin():
                first = await CommunityApplication(database).claim_username(actor, "Retry_User")
            async with sessions() as database, database.begin():
                retry = await CommunityApplication(database).claim_username(actor, " retry_user ")
            assert retry == first

            with pytest.raises(UsernameAlreadyClaimed):
                async with sessions() as database, database.begin():
                    await CommunityApplication(database).claim_username(actor, "other_user")

            async with sessions() as database:
                row = await database.scalar(
                    select(AcademyPublicProfile).where(
                        AcademyPublicProfile.tenant_id == state.tenant_id,
                        AcademyPublicProfile.person_id == actor.person_id,
                    )
                )
                assert row is not None and row.username == "retry_user"
                assert (
                    await _event_count(database, state.tenant_id, "community.username_claimed") == 1
                )
        finally:
            await engine.dispose()

    _run_async(run())


def test_username_reuse_is_academy_scoped_and_profiles_do_not_leak_between_people(
    postgres_harness,
) -> None:  # noqa: F811
    async def run() -> None:
        engine = create_async_engine(postgres_harness.schema_url, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)
            actor = state.actors[0]
            async with sessions() as database, database.begin():
                await CommunityApplication(database).claim_username(actor, "Academy_Name")
                second_tenant_id = uuid4()
                database.add(
                    Tenant(
                        id=second_tenant_id,
                        slug=f"community-{second_tenant_id.hex}",
                        name="Second isolated academy",
                    )
                )
                database.add(
                    Membership(
                        tenant_id=second_tenant_id,
                        person_id=actor.person_id,
                        role="learner",
                    )
                )
                await database.flush()
                second_session_id = uuid4()
                database.add(
                    IdentitySession(
                        id=second_session_id,
                        person_id=actor.person_id,
                        selected_tenant_id=second_tenant_id,
                        token_hash=hashlib.sha256(second_session_id.bytes).digest(),
                        created_at=NOW,
                        expires_at=NOW + timedelta(hours=1),
                    )
                )
                await database.flush()
                second_actor = ActorContext(
                    person_id=actor.person_id,
                    session_id=second_session_id,
                    tenant_id=second_tenant_id,
                )
                second_profile = await CommunityApplication(database).claim_username(
                    second_actor, " academy_name "
                )
                assert second_profile["username"] == "academy_name"

            async with sessions() as database:
                rows = list(
                    await database.scalars(
                        select(AcademyPublicProfile)
                        .where(AcademyPublicProfile.person_id == actor.person_id)
                        .order_by(AcademyPublicProfile.tenant_id)
                    )
                )
                assert len(rows) == 2
                assert {row.username for row in rows} == {"academy_name"}
                other_person_profile = await CommunityApplication(database).profile(
                    ActorContext(
                        person_id=state.actors[1].person_id,
                        session_id=state.actors[1].session_id,
                        tenant_id=state.tenant_id,
                    )
                )
                assert other_person_profile["username"] is None
                assert (
                    await _event_count(database, state.tenant_id, "community.username_claimed") == 1
                )
                assert (
                    await _event_count(database, second_tenant_id, "community.username_claimed")
                    == 1
                )
        finally:
            await engine.dispose()

    _run_async(run())


def test_leaderboard_opt_in_out_uses_revisions_and_appends_one_audit_per_change(
    postgres_harness,
) -> None:  # noqa: F811
    async def run() -> None:
        engine = create_async_engine(postgres_harness.schema_url, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)
            actor = state.actors[0]
            async with sessions() as database, database.begin():
                await CommunityApplication(database).claim_username(actor, "Revision_User")
            async with sessions() as database, database.begin():
                joined = await CommunityApplication(database).set_leaderboard_opt_in(
                    actor, opted_in=True, expected_revision=1
                )
                assert joined["leaderboard_opted_in"] is True
                assert joined["revision"] == 2
            async with sessions() as database, database.begin():
                retry = await CommunityApplication(database).set_leaderboard_opt_in(
                    actor, opted_in=True, expected_revision=1
                )
                assert retry["revision"] == 2
                withdrawn = await CommunityApplication(database).set_leaderboard_opt_in(
                    actor, opted_in=False, expected_revision=2
                )
                assert withdrawn["leaderboard_opted_in"] is False
                assert withdrawn["revision"] == 3

            with pytest.raises(CommunityRevisionConflict):
                async with sessions() as database, database.begin():
                    await CommunityApplication(database).set_leaderboard_opt_in(
                        actor, opted_in=True, expected_revision=2
                    )

            async with sessions() as database:
                row = await database.scalar(
                    select(AcademyPublicProfile).where(
                        AcademyPublicProfile.tenant_id == state.tenant_id,
                        AcademyPublicProfile.person_id == actor.person_id,
                    )
                )
                assert row is not None
                assert (row.leaderboard_opted_in, row.revision) == (False, 3)
                assert (
                    await _event_count(database, state.tenant_id, "community.leaderboard_joined")
                    == 1
                )
                assert (
                    await _event_count(database, state.tenant_id, "community.leaderboard_withdrawn")
                    == 1
                )
        finally:
            await engine.dispose()

    _run_async(run())


def test_leaderboard_filters_to_active_learners_and_ranks_earned_xp_with_tied_pagination(
    postgres_harness,
) -> None:  # noqa: F811
    async def run() -> None:
        engine = create_async_engine(
            postgres_harness.schema_url, pool_size=4, max_overflow=0, hide_parameters=True
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)
            high, tied = state.actors
            async with sessions() as database, database.begin():
                inactive = await _add_person_and_membership(
                    database,
                    tenant_id=state.tenant_id,
                    email="inactive-community@example.test",
                    membership_status=MembershipStatus.INACTIVE.value,
                )
                suspended = await _add_person_and_membership(
                    database,
                    tenant_id=state.tenant_id,
                    email="suspended-community@example.test",
                    person_status=PersonStatus.SUSPENDED.value,
                )
                unverified = await _add_person_and_membership(
                    database,
                    tenant_id=state.tenant_id,
                    email="unverified-community@example.test",
                    email_verified=False,
                )
                admin = await _add_person_and_membership(
                    database,
                    tenant_id=state.tenant_id,
                    email="admin-community@example.test",
                    role="admin",
                )
                zero_xp = await _add_person_and_membership(
                    database,
                    tenant_id=state.tenant_id,
                    email="zero-xp-community@example.test",
                )
                public_tied = await _add_person_and_membership(
                    database,
                    tenant_id=state.tenant_id,
                    email="public-tie-community@example.test",
                )
                for actor, username in (
                    (high, "high_scorer"),
                    (tied, "alpha_tie"),
                    (public_tied, "beta_tie"),
                    (inactive, "inactive_user"),
                    (suspended, "suspended_user"),
                    (unverified, "unverified_user"),
                    (admin, "admin_member"),
                    (zero_xp, "zero_user"),
                ):
                    await _add_profile(database, actor, username)

                audit_event_id = await database.scalar(
                    select(AuditEvent.id)
                    .where(AuditEvent.tenant_id == state.tenant_id)
                    .order_by(AuditEvent.sequence_no)
                    .limit(1)
                )
                assert isinstance(audit_event_id, UUID)
                set_version = PracticeSetVersion(
                    id=uuid4(),
                    tenant_id=state.tenant_id,
                    family_id="community-fixture",
                    definition_version="1",
                    content_digest="c" * 64,
                    snapshot={"items": []},
                    created_at=NOW,
                )
                database.add(set_version)
                await database.flush()
                await _add_reward(
                    database,
                    actor=high,
                    set_version_id=set_version.id,
                    audit_event_id=audit_event_id,
                    index=0,
                )
                await _add_reward(
                    database,
                    actor=high,
                    set_version_id=set_version.id,
                    audit_event_id=audit_event_id,
                    index=1,
                )
                await _add_reward(
                    database,
                    actor=tied,
                    set_version_id=set_version.id,
                    audit_event_id=audit_event_id,
                    index=0,
                )
                await _add_reward(
                    database,
                    actor=public_tied,
                    set_version_id=set_version.id,
                    audit_event_id=audit_event_id,
                    index=0,
                )
                for index, actor in enumerate((inactive, suspended, unverified, admin), start=2):
                    await _add_reward(
                        database,
                        actor=actor,
                        set_version_id=set_version.id,
                        audit_event_id=audit_event_id,
                        index=index,
                    )
                await _add_reward(
                    database,
                    actor=zero_xp,
                    set_version_id=set_version.id,
                    audit_event_id=audit_event_id,
                    index=6,
                    xp=0,
                    credits=40,
                    kind="weekly_rhythm",
                )

            async with sessions() as database, database.begin():
                first_page = await CommunityApplication(database).leaderboard(
                    high, limit=2, cursor=None
                )
                second_page = await CommunityApplication(database).leaderboard(
                    high,
                    limit=2,
                    cursor=first_page["next_cursor"],
                )

            assert [item["username"] for item in first_page["items"]] == [
                "high_scorer",
                "alpha_tie",
            ]
            assert [item["rank"] for item in first_page["items"]] == [1, 2]
            assert first_page["items"][0]["is_current_learner"] is True
            assert [item["username"] for item in second_page["items"]] == ["beta_tie"]
            assert second_page["items"][0]["rank"] == 2
            assert second_page["next_cursor"] is None
            cursor = first_page["next_cursor"]
            assert isinstance(cursor, str)
            assert decode_cursor(cursor).username == "alpha_tie"
            assert decode_cursor(cursor).xp == 30
            serialized = json.dumps((first_page, second_page), sort_keys=True)
            assert "@example.test" not in serialized
            assert str(state.tenant_id) not in serialized
            assert all(str(actor.person_id) not in serialized for actor in state.actors)
            assert all(
                private not in serialized
                for private in (
                    "inactive-community@example.test",
                    "suspended-community@example.test",
                    "unverified-community@example.test",
                    "admin-community@example.test",
                    "zero-xp-community@example.test",
                )
            )
            assert all(
                key == {"rank", "username", "xp_total", "is_current_learner"}
                for page in (first_page, second_page)
                for key in (set(item) for item in page["items"])
            )
            assert all(
                excluded not in serialized
                for excluded in (
                    "inactive_user",
                    "suspended_user",
                    "unverified_user",
                    "admin_member",
                    "zero_user",
                )
            )

            async with sessions() as database, database.begin():
                withdrawn = await CommunityApplication(database).set_leaderboard_opt_in(
                    public_tied,
                    opted_in=False,
                    expected_revision=1,
                )
                assert (withdrawn["leaderboard_opted_in"], withdrawn["revision"]) == (
                    False,
                    2,
                )
                after_withdrawal = await CommunityApplication(database).leaderboard(
                    high, limit=10, cursor=None
                )
            assert all(item["username"] != "beta_tie" for item in after_withdrawal["items"])
        finally:
            await engine.dispose()

    _run_async(run())


def test_academy_public_profiles_migration_matches_orm_metadata(postgres_harness) -> None:  # noqa: F811
    table_name = "academy_public_profiles"
    metadata = model_metadata()
    model_table = metadata.tables[table_name]
    inspector = inspect(postgres_harness.engine)

    assert {column["name"] for column in inspector.get_columns(table_name)} == set(
        model_table.columns.keys()
    )

    database_foreign_keys = {
        item["name"]: (
            tuple(item["constrained_columns"]),
            item["referred_table"],
            tuple(item["referred_columns"]),
        )
        for item in inspector.get_foreign_keys(table_name)
    }
    model_foreign_keys = {
        constraint.name: (
            tuple(constraint.column_keys),
            constraint.elements[0].column.table.name,
            tuple(element.column.name for element in constraint.elements),
        )
        for constraint in model_table.foreign_key_constraints
    }
    assert database_foreign_keys == model_foreign_keys

    database_uniques = {
        item["name"]: tuple(item["column_names"])
        for item in inspector.get_unique_constraints(table_name)
    }
    model_uniques = {
        constraint.name: tuple(constraint.columns.keys())
        for constraint in model_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert database_uniques == model_uniques

    database_checks = {item["name"] for item in inspector.get_check_constraints(table_name)}
    model_checks = {
        constraint.name
        for constraint in model_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert database_checks == model_checks

    database_indexes = {
        item["name"]: tuple(item["column_names"])
        for item in inspector.get_indexes(table_name)
        if not item.get("duplicates_constraint")
    }
    model_indexes = {index.name: tuple(index.columns.keys()) for index in model_table.indexes}
    assert database_indexes == model_indexes

    def include_object(obj: object, name: str | None, kind: str, *_args: object) -> bool:
        if kind == "table":
            return name == table_name
        parent = getattr(obj, "table", None)
        return parent is None or parent.name == table_name

    with postgres_harness.engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"include_object": include_object, "compare_type": True},
        )
        assert compare_metadata(context, metadata) == []


def test_community_public_identity_is_immutable_in_orm_and_postgresql(
    postgres_harness,
) -> None:  # noqa: F811
    async def run() -> None:
        engine = create_async_engine(postgres_harness.schema_url, hide_parameters=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)
            actor = state.actors[0]
            async with sessions() as database, database.begin():
                await CommunityApplication(database).claim_username(actor, "Immutable_User")

            async with sessions() as database:
                row = await database.scalar(
                    select(AcademyPublicProfile).where(
                        AcademyPublicProfile.tenant_id == state.tenant_id,
                        AcademyPublicProfile.person_id == actor.person_id,
                    )
                )
                assert row is not None
                with pytest.raises(CommunityProfileMutationError, match="immutable"):
                    async with database.begin_nested():
                        row.username = "changed_user"
                        await database.flush()
                await database.rollback()

            for statement in (
                update(AcademyPublicProfile)
                .where(
                    AcademyPublicProfile.tenant_id == state.tenant_id,
                    AcademyPublicProfile.person_id == actor.person_id,
                )
                .values(username="changed_user"),
                AcademyPublicProfile.__table__.delete().where(
                    AcademyPublicProfile.tenant_id == state.tenant_id,
                    AcademyPublicProfile.person_id == actor.person_id,
                ),
            ):
                async with sessions() as database:
                    with pytest.raises(DBAPIError):
                        async with database.begin_nested():
                            await database.execute(statement)
                    await database.rollback()

            async with sessions() as database:
                row = await database.scalar(
                    select(AcademyPublicProfile).where(
                        AcademyPublicProfile.tenant_id == state.tenant_id,
                        AcademyPublicProfile.person_id == actor.person_id,
                    )
                )
                assert row is not None and row.username == "immutable_user"
        finally:
            await engine.dispose()

    _run_async(run())
