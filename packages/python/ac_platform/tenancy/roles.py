"""What each organisation role may do, in one place.

Owner, 25 Oct 2026: "only two options that is admin and member, there are many roles
businesses need and this admin is not to be made to all" (design:
docs/product/roles-owner-profile-pulse.md, section 1).

This first version moves every Sales X-Ray organisation check that named owner or admin
here, with exactly today's answers: owners and admins manage, members work their own
leads, and only the owner pays. The next slice adds Sales manager, Viewer and Finance by
giving them capabilities here, not by editing the checks again. The learner academy's
roles and the operations team keep their own checks.
"""

from __future__ import annotations

from typing import Final, Literal

Capability = Literal[
    "org.manage",  # settings, integrations, AI apps, product notices for admins
    "members.manage",  # invite, change a role, remove; coaching duties
    "billing.view",
    "billing.pay",
    "team.view",  # the team's leads, calls, reports and insights
    "leads.manage",  # assign, reassign, bulk, targets, SLA escalation
    "leads.work",  # own leads, calls and tasks
]

# The roles an organisation's members have, and the ones an owner or admin may give
# (ownership moves only by transfer).
ORG_ROLES: Final[tuple[str, ...]] = ("owner", "admin", "member")
ASSIGNABLE_ROLES: Final[tuple[str, ...]] = ("admin", "member")

_MANAGE: Final = frozenset(
    {"org.manage", "members.manage", "billing.view", "team.view", "leads.manage", "leads.work"}
)
CAPABILITIES: Final[dict[str, frozenset[str]]] = {
    "owner": _MANAGE | {"billing.pay"},
    "admin": _MANAGE,
    "member": frozenset({"leads.work"}),
}


def can(role: str | None, capability: Capability) -> bool:
    """Whether a member with this role may do this; unknown roles may do nothing."""
    return capability in CAPABILITIES.get(role or "", frozenset())


def roles_with(capability: Capability) -> tuple[str, ...]:
    """The roles that may, in ``ORG_ROLES`` order (for a query's ``IN``)."""
    return tuple(role for role in ORG_ROLES if can(role, capability))


__all__ = ["ASSIGNABLE_ROLES", "CAPABILITIES", "ORG_ROLES", "Capability", "can", "roles_with"]
