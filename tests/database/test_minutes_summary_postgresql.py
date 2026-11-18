"""Minutes given, used and left read from the real ledger, with fictional members only."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.conversation_intelligence.minutes_summary import (
    seller_minutes,
    workspace_minutes,
)
from tests.database.test_billing_ledger_postgresql import source
from tests.database.test_billing_org_pool_postgresql import acquisition, fixtures, grant
from tests.database.test_billing_org_pool_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_postgresql import run


def test_pool_members_and_the_next_expiry_match_what_uploads_are_admitted_against(
    postgres_harness,
):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            first, second, operations = await fixtures(engine)
            ends = datetime.now(UTC) + timedelta(days=5)
            async with AsyncSession(engine) as db, db.begin():
                await grant(db, first, operations, 1_800, personal=True)
                await grant(db, first, operations, 600, expires_at=ends)
                app = acquisition(db, first, operations)
                settled = await app.reserve(source(300), actor=first.actor)
                await app.settle(settled, charged_seconds=300, receipt_sha256="a" * 64)
                await acquisition(db, second, operations).reserve(source(120), actor=second.actor)
            async with AsyncSession(engine) as db, db.begin():
                allowance = await acquisition(db, second, operations).allowance(actor=second.actor)
                now = datetime.now(UTC)
                options = {
                    "now": now,
                    "operations_tenant_id": operations.tenant_id,
                    "public_learner_tenant_id": operations.tenant_id,
                }
                everyone = await workspace_minutes(db, tenant_id=first.tenant_id, **options)
                theirs = await seller_minutes(
                    db, tenant_id=second.tenant_id, person_id=second.person_id, **options
                )
            # The same numbers an upload is admitted against.
            assert everyone["granted_seconds"] == allowance["allowance_seconds"] == 2_400
            assert everyone["used_seconds"] == allowance["committed_seconds"] == 420
            assert everyone["left_seconds"] == allowance["available_seconds"] == 1_980
            assert everyone["pending_seconds"] == 120
            # Uses draw on the lot that ends first, so its 180 unused seconds end on its day.
            assert everyone["next_expiry_at"] == ends.isoformat()
            assert everyone["expiring_seconds"] == 180
            members = {item["person_id"]: item for item in everyone["members"]}
            assert members[str(first.person_id)] | {"name": None} == {
                "person_id": str(first.person_id),
                "name": None,
                "role": "member",
                "granted_seconds": 1_800,
                "used_seconds": 300,
                "pending_seconds": 0,
            }
            assert members[str(second.person_id)]["granted_seconds"] == 0
            assert members[str(second.person_id)]["used_seconds"] == 120
            assert members[str(second.person_id)]["pending_seconds"] == 120
            assert everyone["others_used_seconds"] == 0 and everyone["truncated"] is False
            assert set(members) == {str(first.person_id), str(second.person_id)}
            assert theirs["scope"] == "organisation"
            assert theirs["left_seconds"] == 1_980
            assert theirs["mine"] == {"used_seconds": 120, "pending_seconds": 120}
            assert not any("price" in key or "inr" in key for key in everyone)
        finally:
            await engine.dispose()

    run(exercise())
