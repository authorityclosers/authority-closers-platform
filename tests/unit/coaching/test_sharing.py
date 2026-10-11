"""Owner decisions 10 Oct: private by default, one revocable share, assigned coaches."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from ac_platform.coaching.sharing import (
    CoachAssignment,
    CoachDuty,
    CoachingShare,
    Viewer,
    assigned_reps,
    may_manage_coaching_duties,
    rep_coaching_access,
)

NOW = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)
TENANT, OTHER_TENANT = UUID(int=1), UUID(int=2)
REP, COACH, ADMIN, OWNER, MEMBER = (UUID(int=n) for n in range(10, 15))


def viewer(person: UUID, role: str | None = "member", tenant: UUID = TENANT) -> Viewer:
    return Viewer(person_id=person, tenant_id=tenant, org_role=role)  # type: ignore[arg-type]


def share(revoked: datetime | None = None, tenant: UUID = TENANT) -> CoachingShare:
    return CoachingShare(
        tenant_id=tenant,
        share_id=UUID(int=99),
        rep_person_id=REP,
        shared_at=NOW - timedelta(days=1),
        revoked_at=revoked,
    )


DUTY = CoachDuty(
    tenant_id=TENANT, coach_person_id=COACH, granted_by=ADMIN, granted_at=NOW - timedelta(days=2)
)
ASSIGNED = CoachAssignment(
    tenant_id=TENANT,
    coach_person_id=COACH,
    rep_person_id=REP,
    assigned_by=ADMIN,
    assigned_at=NOW - timedelta(days=2),
)


def access(v: Viewer, **records: object) -> str:
    options: dict[str, object] = {
        "rep_is_member": True,
        "shares": (),
        "duties": (DUTY,),
        "assignments": (ASSIGNED,),
        "now": NOW,
    }
    options.update(records)
    return rep_coaching_access(v, REP, **options)  # type: ignore[arg-type]


def test_private_by_default_even_for_owners_admins_and_assigned_coaches() -> None:
    assert access(viewer(REP)) == "own"
    for person, role in ((OWNER, "owner"), (ADMIN, "admin"), (COACH, "member"), (MEMBER, "member")):
        assert access(viewer(person, role)) == "denied"


def test_one_share_opens_to_admins_and_assigned_coaches_only() -> None:
    shares = (share(),)
    assert access(viewer(OWNER, "owner"), shares=shares) == "shared_with_admin"
    assert access(viewer(ADMIN, "admin"), shares=shares) == "shared_with_admin"
    assert access(viewer(COACH), shares=shares) == "shared_with_coach"
    # An ordinary teammate never sees it, shared or not.
    assert access(viewer(MEMBER), shares=shares) == "denied"


def test_revoking_a_share_assignment_or_duty_ends_access_immediately() -> None:
    revoked = (share(revoked=NOW),)
    assert access(viewer(ADMIN, "admin"), shares=revoked) == "denied"
    assert access(viewer(COACH), shares=revoked) == "denied"
    shares = (share(),)
    ended = ASSIGNED.model_copy(update={"revoked_at": NOW - timedelta(seconds=1)})
    assert access(viewer(COACH), shares=shares, assignments=(ended,)) == "denied"
    lost_duty = DUTY.model_copy(update={"revoked_at": NOW})
    assert access(viewer(COACH), shares=shares, duties=(lost_duty,)) == "denied"
    # A share revoked in the future is still active now.
    later = (share(revoked=NOW + timedelta(hours=1)),)
    assert access(viewer(COACH), shares=later) == "shared_with_coach"


def test_other_workspaces_and_former_members_never_read() -> None:
    shares = (share(),)
    assert access(viewer(ADMIN, "admin", OTHER_TENANT), shares=shares) == "denied"
    assert access(viewer(ADMIN, "admin"), shares=(share(tenant=OTHER_TENANT),)) == "denied"
    assert access(viewer(ADMIN, None), shares=shares) == "denied"
    assert access(viewer(ADMIN, "admin"), shares=shares, rep_is_member=False) == "denied"


def test_a_coach_duty_grants_no_management_and_needs_membership() -> None:
    assert not may_manage_coaching_duties(viewer(COACH))
    assert may_manage_coaching_duties(viewer(ADMIN, "admin"))
    assert may_manage_coaching_duties(viewer(OWNER, "owner"))
    assert assigned_reps(viewer(COACH), (DUTY,), (ASSIGNED,), NOW) == {REP}
    assert assigned_reps(viewer(COACH, None), (DUTY,), (ASSIGNED,), NOW) == frozenset()
    assert assigned_reps(viewer(COACH), (), (ASSIGNED,), NOW) == frozenset()


def test_records_reject_impossible_histories() -> None:
    with pytest.raises(ValidationError):
        share(revoked=NOW - timedelta(days=2))
    with pytest.raises(ValidationError):
        CoachAssignment(
            tenant_id=TENANT,
            coach_person_id=REP,
            rep_person_id=REP,
            assigned_by=ADMIN,
            assigned_at=NOW,
        )
