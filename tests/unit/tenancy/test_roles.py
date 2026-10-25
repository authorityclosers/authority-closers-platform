"""The organisation role map (tenancy/roles.py). Roles A (25 Oct 2026) gave exactly the
answers of the checks it replaced; Roles B adds Sales manager, Viewer and Finance
(design docs/product/roles-owner-profile-pulse.md, section 1) without changing what
owners, admins and sellers may do, and anything else may do nothing."""

from __future__ import annotations

import pytest

from ac_platform.tenancy.roles import (
    ASSIGNABLE_ROLES,
    ORG_ROLES,
    READ_ONLY_ROLES,
    can,
    read_only_refusal,
    roles_with,
)

CAPABILITIES = (
    "org.manage",
    "members.manage",
    "billing.view",
    "billing.pay",
    "team.view",
    "leads.manage",
    "leads.delete",
    "leads.work",
)


@pytest.mark.parametrize(
    ("capability", "roles"),
    [
        ("org.manage", ("owner", "admin")),
        ("members.manage", ("owner", "admin")),
        ("billing.view", ("owner", "admin", "finance")),
        ("billing.pay", ("owner", "finance")),
        ("team.view", ("owner", "admin", "manager", "viewer")),
        ("leads.manage", ("owner", "admin", "manager")),
        ("leads.delete", ("owner", "admin")),
        ("leads.work", ("owner", "admin", "manager", "member")),
    ],
)
def test_who_may_do_what(capability: str, roles: tuple[str, ...]) -> None:
    assert roles_with(capability) == roles  # type: ignore[arg-type]
    for role in ORG_ROLES:
        assert can(role, capability) is (role in roles)  # type: ignore[arg-type]


@pytest.mark.parametrize("role", [None, "", "learner", "support", "processing", "OWNER"])
def test_anything_else_may_do_nothing(role: str | None) -> None:
    assert not any(can(role, capability) for capability in CAPABILITIES)  # type: ignore[arg-type]
    assert not read_only_refusal(role, "POST", "/v1/lead-desk/leads")


def test_ownership_is_never_given_by_a_role_change() -> None:
    assert ORG_ROLES == ("owner", "admin", "manager", "member", "viewer", "finance")
    assert ASSIGNABLE_ROLES == ("admin", "manager", "member", "viewer", "finance")
    assert sorted(READ_ONLY_ROLES) == ["finance", "viewer"]


@pytest.mark.parametrize(
    ("role", "method", "path", "refused"),
    [
        # Viewers and Finance read everything they can see.
        ("viewer", "GET", "/v1/lead-desk/leads", False),
        ("finance", "HEAD", "/v1/organisation", False),
        # ... and change nothing else: a route nobody listed stays closed.
        ("viewer", "POST", "/v1/lead-desk/leads", True),
        ("viewer", "PATCH", "/v1/organisation/settings", True),
        ("viewer", "DELETE", "/v1/lead-desk/leads/1", True),
        ("viewer", "POST", "/v1/some-new-route", True),
        ("viewer", "POST", "/v1/me", True),
        ("viewer", "POST", "/v1/me/coaching/notes", True),
        ("viewer", "POST", "/v1/checkout", True),
        ("finance", "POST", "/v1/lead-desk/leads", True),
        ("finance", "POST", "/v1/payments/1/refund", True),
        # Their own account, session and workspace; notices; bug reports and feedback.
        ("viewer", "PUT", "/v1/me/sales-xray-profile/details", False),
        ("viewer", "POST", "/v1/auth/logout", False),
        ("viewer", "POST", "/v1/context", False),
        ("viewer", "POST", "/v1/sessions/1/revoke", False),
        ("viewer", "POST", "/v1/me/consent/renew", False),
        ("finance", "POST", "/v1/bug-reports", False),
        ("viewer", "POST", "/v1/notifications/read-all", False),
        # A prefix is a whole path segment.
        ("viewer", "POST", "/v1/contextual", True),
        ("viewer", "POST", "/v1/feedbacks", True),
        # Finance pays.
        ("finance", "POST", "/v1/checkout", False),
        ("finance", "POST", "/v1/orders/1/verify", False),
        ("finance", "POST", "/v1/subscriptions/1/cancel", False),
        # Everyone else is not read-only.
        ("manager", "POST", "/v1/lead-desk/leads", False),
        ("member", "DELETE", "/v1/lead-desk/leads/1", False),
    ],
)
def test_read_only_roles_change_only_their_own(
    role: str, method: str, path: str, refused: bool
) -> None:
    assert read_only_refusal(role, method, path) is refused
