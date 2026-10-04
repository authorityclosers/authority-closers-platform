"""Shared, fail-closed organisation seat exemptions from pinned approvals."""

from datetime import UTC, datetime
from uuid import UUID

from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy


def seat_exempt(tenant_id: UUID, *, policy: object, environment: str) -> bool:
    try:
        if not isinstance(policy, InternalTesterPolicy):
            return False
        bundle = policy.loader().current(int(datetime.now(UTC).timestamp()), environment)
        return any(item.tenant_id == tenant_id for item in bundle.organisation_seat_exemptions)
    except Exception:
        # An unavailable or stale pinned approval cannot waive paid seats.
        return False
