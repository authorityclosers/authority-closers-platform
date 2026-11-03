"""Coaching reads its reports' access in one query (orchestrator's go, 3 Nov 2026), and who sees
which report stays exactly as it was: a seller sees only their own, an owner or admin their own
organisation's (with organisation read), and nothing crosses organisations. A permission revoked
leaves its report out."""

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_coaching_postgresql import draft_for, install
from tests.database.test_coaching_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_prospect_store_postgresql import direct_call


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def team(postgres_harness: Any, tmp_path: Path) -> tuple[Any, Any, UUID, UUID, UUID]:
    """An organisation: its owner and a seller, each with one report-ready call."""
    setup = await _setup(postgres_harness, tmp_path)
    async with setup.sessions() as db, db.begin():
        db.add(
            Organisation(
                tenant_id=setup.state.tenant_id,
                created_by_person_id=setup.state.person_id,
                creation_command_id=uuid4(),
                domain_verification_token=uuid4().hex + uuid4().hex,
            )
        )
        await db.execute(
            update(Membership)
            .where(Membership.person_id == setup.state.person_id)
            .values(role="owner")
        )
    install(setup, organisation=True)
    owners = await direct_call(setup)
    await draft_for(setup, owners)
    seller = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
    sellers = await direct_call(setup, seller.actor)
    sellers_recording, _ = await draft_for(setup, sellers)
    return setup, seller, owners, sellers, sellers_recording


async def readable(
    setup: Any,
    actor: ActorContext,
    calls: list[UUID],
    *,
    organisation: bool,
    tenant_id: UUID | None = None,
) -> set[UUID]:
    async with setup.sessions() as db, db.begin():
        reports = AcquisitionReports(
            GuestOwnership(setup.factory(db, tenant_id or setup.state.tenant_id))
        )
        found = await reports.readable_recordings(
            calls,
            actor=actor,
            shared_identity_locks=True,
            allow_organisation_read=organisation,
        )
    return set(found)


def test_a_seller_reads_only_their_own_reports(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup, seller, owners, sellers, _ = await team(postgres_harness, tmp_path)
        try:
            calls = [owners, sellers]
            # Organisation read asked for or not: a seller is no organisation reader.
            for organisation in (False, True):
                assert await readable(setup, seller.actor, calls, organisation=organisation) == {
                    sellers
                }
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_an_owner_or_admin_reads_their_teams_reports_and_a_revoked_one_never(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup, _, owners, sellers, sellers_recording = await team(postgres_harness, tmp_path)
        try:
            calls, owner = [owners, sellers], setup.state.actor
            # Their own calls only, unless organisation read is asked for.
            assert await readable(setup, owner, calls, organisation=False) == {owners}
            assert await readable(setup, owner, calls, organisation=True) == {owners, sellers}
            for role, team_reads in (("admin", True), ("member", False)):
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(Membership.person_id == setup.state.person_id)
                        .values(role=role)
                    )
                expected = {owners, sellers} if team_reads else {owners}
                assert await readable(setup, owner, calls, organisation=True) == expected
            # A permission revoked leaves its report out, for everyone.
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(Membership.person_id == setup.state.person_id)
                    .values(role="owner")
                )
                recording = await db.get(ConversationRecording, sellers_recording)
                assert recording is not None
                permission = await db.scalar(
                    select(ConversationPermission).where(
                        ConversationPermission.id == recording.permission_id
                    )
                )
                assert permission is not None
                permission.revoked_at = setup.state.now
            assert await readable(setup, owner, calls, organisation=True) == {owners}
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_no_report_crosses_organisations(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup, _, owners, sellers, _ = await team(postgres_harness, tmp_path)
        try:
            calls = [owners, sellers]
            # Another organisation's admin, through their own organisation or this one.
            other = await seed(setup.engine, role="admin")
            async with setup.sessions() as db, db.begin():
                db.add(
                    Organisation(
                        tenant_id=other.tenant_id,
                        created_by_person_id=other.person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token=uuid4().hex + uuid4().hex,
                    )
                )
            for tenant_id in (other.tenant_id, setup.state.tenant_id):
                assert (
                    await readable(
                        setup, other.actor, calls, organisation=True, tenant_id=tenant_id
                    )
                    == set()
                )
            # This organisation's owner, through the other organisation.
            assert (
                await readable(
                    setup,
                    setup.state.actor,
                    calls,
                    organisation=True,
                    tenant_id=other.tenant_id,
                )
                == set()
            )
        finally:
            await setup.engine.dispose()

    run(exercise())
