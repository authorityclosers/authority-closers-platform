"""What each organisation role may do, in one place.

Owner, 25 Oct 2026: "only two options that is admin and member, there are many roles
businesses need and this admin is not to be made to all" (design:
docs/product/roles-owner-profile-pulse.md, section 1).

Every Sales X-Ray organisation check that named owner or admin asks this map (Roles A,
with exactly the answers of the time). Roles B (migration 0136) adds three roles by giving
them capabilities here:

- Sales manager (``manager``): the team's leads and calls, assigning and bulk changes;
  not members, settings, integrations, billing or deleting leads.
- Viewer (``viewer``): reads the team's work and changes nothing.
- Finance (``finance``): billing only.

Sellers keep the stored value ``member``. Viewer and Finance are read-only, enforced once
in ``require_actor`` (``read_only_refusal``). The learner academy's roles and the
operations team keep their own checks.
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
    "leads.delete",
    "leads.work",  # own leads, calls and tasks
]

# The roles an organisation's members have, and the ones an owner or admin may give
# (ownership moves only by transfer). The Literals type them where they cross an API.
OrgRoleName = Literal["owner", "admin", "manager", "member", "viewer", "finance"]
AssignableRoleName = Literal["admin", "manager", "member", "viewer", "finance"]
ORG_ROLES: Final[tuple[str, ...]] = ("owner", "admin", "manager", "member", "viewer", "finance")
ASSIGNABLE_ROLES: Final[tuple[str, ...]] = ("admin", "manager", "member", "viewer", "finance")
# Roles that change nothing outside their own profile (and, for Finance, billing).
READ_ONLY_ROLES: Final[frozenset[str]] = frozenset({"viewer", "finance"})

_LEADS: Final = frozenset({"team.view", "leads.manage", "leads.work"})
_MANAGE: Final = _LEADS | {"org.manage", "members.manage", "billing.view", "leads.delete"}
CAPABILITIES: Final[dict[str, frozenset[str]]] = {
    "owner": _MANAGE | {"billing.pay"},
    "admin": _MANAGE,
    "manager": _LEADS,
    "member": frozenset({"leads.work"}),
    "viewer": frozenset({"team.view"}),
    "finance": frozenset({"billing.view", "billing.pay"}),
}


def can(role: str | None, capability: Capability) -> bool:
    """Whether a member with this role may do this; unknown roles may do nothing."""
    return capability in CAPABILITIES.get(role or "", frozenset())


def roles_with(capability: Capability) -> tuple[str, ...]:
    """The roles that may, in ``ORG_ROLES`` order (for a query's ``IN``)."""
    return tuple(role for role in ORG_ROLES if can(role, capability))


_READS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
# What a read-only member may still change: their own account and session, the
# workspace they are in, notices they have read, and bug reports and feedback. Anything
# not listed stays closed, so a forgotten route is refused, not opened.
_OWN_WRITES: Final[tuple[str, ...]] = (
    "/v1/auth",
    "/v1/context",
    "/v1/sessions",
    "/v1/me/sales-xray-profile",
    "/v1/me/consent",
    "/v1/me/sales-xray-workspaces",
    "/v1/me/sign-in-methods",
    "/v1/me/account-deletion",
    "/v1/me/app-updates",
    "/v1/me/connected-apps",
    "/v1/updates/seen",
    "/v1/notifications/read",
    "/v1/notifications/read-all",
    "/v1/bug-reports",
    "/v1/feedback",
    "/v1/telemetry",
)
# Finance pays: checkout, verifying its own order, and a subscription's cancellation.
_BILLING_WRITES: Final[tuple[str, ...]] = ("/v1/checkout", "/v1/orders", "/v1/subscriptions")


def read_only_refusal(role: str | None, method: str, path: str) -> bool:
    """Whether a request is a change that this role may not make (Viewer, Finance)."""
    if role not in READ_ONLY_ROLES or method.upper() in _READS:
        return False
    allowed = _OWN_WRITES + (_BILLING_WRITES if role == "finance" else ())
    return not any(path == prefix or path.startswith(prefix + "/") for prefix in allowed)


__all__ = [
    "ASSIGNABLE_ROLES",
    "CAPABILITIES",
    "ORG_ROLES",
    "AssignableRoleName",
    "OrgRoleName",
    "READ_ONLY_ROLES",
    "Capability",
    "can",
    "read_only_refusal",
    "roles_with",
]
