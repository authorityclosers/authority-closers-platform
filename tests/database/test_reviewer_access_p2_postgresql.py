"""PostgreSQL proof for reviewer deactivation boundaries."""

from __future__ import annotations

from uuid import UUID

from ac_platform.tenancy.models import Tenant, TenantStatus
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reviews_postgresql import (
    ReviewCase,
    _create_assignment,
    _service,
)

pytest_plugins = ("tests.database.test_conversation_reviews_postgresql",)


def test_reviewer_assignment_listing_hides_inactive_tenant(review_case: ReviewCase) -> None:
    async def exercise() -> None:
        case = review_case
        created = await _create_assignment(case, key="review-assignment-inactive-tenant-listing")
        assignment_id = UUID(created["id"])
        async with case.sessions() as database, database.begin():
            service = _service(database, case)
            visible = await service.reviewer_assignments(case.reviewer_actor)
            assert any(item["id"] == str(assignment_id) for item in visible["items"])

            tenant = await database.get(Tenant, case.prepared.state.tenant_id)
            assert tenant is not None and tenant.status == TenantStatus.ACTIVE.value
            tenant.status = TenantStatus.SUSPENDED.value
            await database.flush()
            hidden = await service.reviewer_assignments(case.reviewer_actor)
            assert all(item["id"] != str(assignment_id) for item in hidden["items"])

            # Keep the module-scoped fixture usable by the remaining PostgreSQL proofs.
            tenant.status = TenantStatus.ACTIVE.value

    run(exercise())
