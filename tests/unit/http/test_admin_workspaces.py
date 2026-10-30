"""Fictional HTTP evidence: Admin's sign-in names a person's own workspaces for what they are."""

from datetime import UTC, datetime
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from ac_platform.http.platform_organisations import AdminWorkspacesResponse
from ac_platform.tenancy.models import Membership, OrganisationDomainSetting, Tenant
from tests.unit.http.test_platform_organisations import state  # noqa: F401
from tests.unit.http.test_workspaces import TOKEN, workspace_state  # noqa: F401


async def own(state, token=TOKEN, *, host="admin.authorityclosers.test", query=""):  # noqa: F811
    headers = {} if token is None else {"cookie": f"ac_session={token}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app), base_url=f"https://{host}"
    ) as client:
        return await client.get("/v1/me/admin-workspaces" + query, headers=headers)


def staff_and_company_named_alike(state):  # noqa: F811
    """The person is an admin of the staff workspace and a member of our company,
    and both are registered as "Other", as two production workspaces read
    "Authority Closers"."""
    with Session(state.engine) as db, db.begin():
        db.add(Membership(tenant_id=state.tenants["Other"], person_id=state.person, role="admin"))
        db.get(Tenant, state.tenants["Alpha"]).name = "Other"
        operator = db.get(Membership, (state.tenants["Alpha"], state.person))
        operator.status, operator.ended_at = "active", None
        db.add(
            OrganisationDomainSetting(
                tenant_id=state.tenants["Alpha"],
                version=1,
                verified_domains=["example.test"],
                auto_join=False,
                proof={},
                command_id=uuid4(),
            )
        )


async def test_needs_a_session_on_the_admin_host(state):  # noqa: F811
    assert (await own(state, token=None)).status_code == 401
    assert (await own(state, host="learner.authorityclosers.test")).status_code == 403
    assert (await own(state, query="?tenant_id=x")).status_code == 422


async def test_names_each_own_workspace_for_what_it_is_without_a_platform_grant(state):  # noqa: F811
    staff_and_company_named_alike(state)

    response = await own(state)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = AdminWorkspacesResponse.model_validate_json(response.text)
    assert (body.person_id, body.session_id, body.selected_tenant_id) == (
        state.person,
        state.session,
        None,
    )
    # Only the person's active memberships in active workspaces; suspended,
    # deleted and other people's workspaces never appear.
    assert [(item.tenant_id, item.name, item.kind) for item in body.workspaces] == [
        (state.tenants["Alpha"], "Other", "company"),
        (state.tenants["Beta"], "Personal accounts", "personal"),
        (state.tenants["Other"], "AC Operations", "operations"),
    ]
    assert len({item.name for item in body.workspaces}) == len(body.workspaces)


async def test_lists_nothing_beyond_the_persons_memberships(state):  # noqa: F811
    now = datetime.now(UTC)
    with Session(state.engine) as db, db.begin():
        for membership in db.query(Membership).filter_by(person_id=state.person):
            membership.status, membership.ended_at = "inactive", now

    response = await own(state)

    assert response.status_code == 200
    assert AdminWorkspacesResponse.model_validate_json(response.text).workspaces == []
