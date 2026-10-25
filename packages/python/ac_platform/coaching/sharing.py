"""Who may read a rep's private Coaching (owner decisions, 10 Oct 2026 15:20 IST).

1. Coaching is private by default. Only the rep's own, currently unrevoked
   share lets anyone else read it: coaches, leadership and organisation
   owners/admins follow the same rule. Membership or org role alone is never
   enough.
2. A coach is a grantable Sales Xray duty. A coach reads only reps currently
   assigned to them, and only what each rep has shared. The duty confers no
   role, membership, billing or grant authority.
3. A Pulse link syncs people, teams and managers only; it never grants admin
   or coach rights here.

Pure policy over already-loaded records. Persistence, routes and audit events
arrive with the reviewed migration slice; callers must load records for the
one tenant being read and pass the database clock.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from ac_platform.coaching.contracts import Model
from ac_platform.tenancy.roles import OrgRoleName, can

OrgRole = OrgRoleName
Access = Literal["own", "shared_with_admin", "shared_with_coach", "denied"]


class _Revocable(Model):
    tenant_id: UUID
    revoked_at: AwareDatetime | None = None

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None or self.revoked_at > now


class CoachingShare(_Revocable):
    """One tap: share my Coaching with my assigned coaches and the org's admins.

    Recipients are evaluated at read time, so removing an assignment or an
    admin role ends their access at once. Revoking supersedes; never delete.
    """

    share_id: UUID
    rep_person_id: UUID
    shared_at: AwareDatetime

    @model_validator(mode="after")
    def ordered(self) -> "CoachingShare":
        if self.revoked_at is not None and self.revoked_at < self.shared_at:
            raise ValueError("A share cannot be revoked before it was made.")
        return self


class CoachDuty(_Revocable):
    coach_person_id: UUID
    granted_by: UUID
    granted_at: AwareDatetime


class CoachAssignment(_Revocable):
    coach_person_id: UUID
    rep_person_id: UUID
    assigned_by: UUID
    assigned_at: AwareDatetime

    @model_validator(mode="after")
    def not_self(self) -> "CoachAssignment":
        if self.coach_person_id == self.rep_person_id:
            raise ValueError("A rep cannot be assigned to coach themselves.")
        return self


class Viewer(Model):
    person_id: UUID
    tenant_id: UUID
    # The viewer's current, active membership role in this tenant, if any.
    org_role: OrgRole | None


def _current[R: _Revocable](
    records: tuple[R, ...], tenant_id: UUID, now: datetime
) -> tuple[R, ...]:
    return tuple(r for r in records if r.tenant_id == tenant_id and r.active(now))


def is_coach(viewer: Viewer, duties: tuple[CoachDuty, ...], now: datetime) -> bool:
    return viewer.org_role is not None and any(
        d.coach_person_id == viewer.person_id for d in _current(duties, viewer.tenant_id, now)
    )


def assigned_reps(
    viewer: Viewer,
    duties: tuple[CoachDuty, ...],
    assignments: tuple[CoachAssignment, ...],
    now: datetime,
) -> frozenset[UUID]:
    """Reps currently assigned to this viewer, only while the duty is held."""
    if not is_coach(viewer, duties, now):
        return frozenset()
    return frozenset(
        a.rep_person_id
        for a in _current(assignments, viewer.tenant_id, now)
        if a.coach_person_id == viewer.person_id
    )


def rep_coaching_access(
    viewer: Viewer,
    rep_person_id: UUID,
    *,
    rep_is_member: bool,
    shares: tuple[CoachingShare, ...],
    duties: tuple[CoachDuty, ...],
    assignments: tuple[CoachAssignment, ...],
    now: datetime,
) -> Access:
    """Decide one read. `rep_is_member` is the rep's current active membership."""
    if viewer.person_id == rep_person_id:
        return "own"
    # No membership in this workspace means no access, whatever was shared.
    if viewer.org_role is None or not rep_is_member:
        return "denied"
    shared = any(s.rep_person_id == rep_person_id for s in _current(shares, viewer.tenant_id, now))
    if not shared:
        return "denied"
    if rep_person_id in assigned_reps(viewer, duties, assignments, now):
        return "shared_with_coach"
    if can(viewer.org_role, "team.view"):
        return "shared_with_admin"
    return "denied"


def may_manage_coaching_duties(actor: Viewer) -> bool:
    """Only current owners/admins grant or revoke the duty and assignments.

    A coach cannot grant duties, assign reps, change roles or touch billing.
    """
    return can(actor.org_role, "members.manage")
