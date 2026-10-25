"""The organisation role map (tenancy/roles.py) gives exactly the answers the checks it
replaced gave (25 Oct 2026): owners and admins manage, members work their own leads,
only the owner pays, and anything else may do nothing."""

from __future__ import annotations

import pytest

from ac_platform.tenancy.roles import ASSIGNABLE_ROLES, ORG_ROLES, can, roles_with


@pytest.mark.parametrize(
    ("capability", "roles"),
    [
        ("org.manage", ("owner", "admin")),
        ("members.manage", ("owner", "admin")),
        ("billing.view", ("owner", "admin")),
        ("billing.pay", ("owner",)),
        ("team.view", ("owner", "admin")),
        ("leads.manage", ("owner", "admin")),
        ("leads.work", ("owner", "admin", "member")),
    ],
)
def test_todays_answers(capability: str, roles: tuple[str, ...]) -> None:
    assert roles_with(capability) == roles  # type: ignore[arg-type]
    for role in ORG_ROLES:
        assert can(role, capability) is (role in roles)  # type: ignore[arg-type]


@pytest.mark.parametrize("role", [None, "", "learner", "support", "processing", "OWNER"])
def test_anything_else_may_do_nothing(role: str | None) -> None:
    assert not any(
        can(role, capability)  # type: ignore[arg-type]
        for capability in (
            "org.manage",
            "members.manage",
            "billing.view",
            "billing.pay",
            "team.view",
            "leads.manage",
            "leads.work",
        )
    )


def test_ownership_is_never_given_by_a_role_change() -> None:
    assert ORG_ROLES == ("owner", "admin", "member")
    assert ASSIGNABLE_ROLES == ("admin", "member")
