"""Move eligibility holds real source and destination fences, grants no access."""

import asyncio
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence.models import ConversationPermission
from ac_platform.kernel.errors import ResourceNotFound
from ac_platform.organisations.call_move import personal_call_move_candidate
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import cancel_pending, run, seed, wait_blocked
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.unit.http.test_organisation_activity import seed_call


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@pytest.mark.parametrize("fence", ["destination_membership", "source_permission"])
def test_candidate_fences_block_changes_then_require_fresh_resolution(postgres_harness, fence):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        task = None
        try:
            owner = await seed(engine)
            operations_id = uuid4()
            async with AsyncSession(engine) as database, database.begin():
                org = await OrganisationService(
                    database,
                    operations_tenant_id=operations_id,
                    public_learner_tenant_id=owner.tenant_id,
                ).create(
                    "Fictional move destination",
                    owner.person_id,
                    uuid4(),
                    "AUT-1694 fixture",
                    actor_person_id=owner.person_id,
                )
            with Session(postgres_harness) as database, database.begin():
                submission_id = seed_call(
                    database,
                    owner.tenant_id,
                    owner.person_id,
                    created_at=owner.now - timedelta(days=2),
                )

            async def candidate(database):
                return await personal_call_move_candidate(
                    database,
                    owner.actor,
                    submission_id=submission_id,
                    destination_tenant_id=org.tenant_id,
                    public_learner_tenant_id=owner.tenant_id,
                    operations_tenant_id=operations_id,
                    at=owner.now,
                )

            waiting_pid = asyncio.get_running_loop().create_future()

            async def change(result):
                async with AsyncSession(engine) as database, database.begin():
                    waiting_pid.set_result(await database.scalar(text("SELECT pg_backend_pid()")))
                    if fence == "destination_membership":
                        await database.execute(
                            update(Membership)
                            .where(
                                Membership.tenant_id == org.tenant_id,
                                Membership.person_id == owner.person_id,
                            )
                            .values(status="inactive", ended_at=owner.now)
                        )
                    else:
                        await database.execute(
                            update(ConversationPermission)
                            .where(ConversationPermission.id == result.permission_id)
                            .values(revoked_at=owner.now)
                        )

            async with AsyncSession(engine) as database, database.begin():
                result = await candidate(database)
                assert result.owner_person_id == owner.person_id != result.processing_person_id
                assert result.source_tenant_id == owner.tenant_id
                task = asyncio.create_task(change(result))
                pid = await asyncio.wait_for(waiting_pid, 5)
                await wait_blocked(engine, pid, task)
            await asyncio.wait_for(task, 5)
            async with AsyncSession(engine) as database, database.begin():
                with pytest.raises(ResourceNotFound):
                    await candidate(database)
        finally:
            await cancel_pending(task)
            await engine.dispose()

    run(exercise())
