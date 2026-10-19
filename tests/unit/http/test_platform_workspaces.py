"""Fictional HTTP evidence: Admin's workspace directory names each workspace for what it is."""

from datetime import UTC, datetime
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.http.platform_organisations import PlatformWorkspacesResponse
from ac_platform.tenancy.models import Organisation, OrganisationDomainSetting
from tests.unit.http.test_platform_organisations import READ, grant, state  # noqa: F401
from tests.unit.http.test_workspaces import TOKEN, workspace_state  # noqa: F401


async def directory(state, token=TOKEN):  # noqa: F811
    headers = {} if token is None else {"cookie": f"ac_session={token}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app),
        base_url="https://admin.authorityclosers.test",
    ) as client:
        return await client.get("/v1/platform/workspaces", headers=headers)


def verified(state, tenant, version, domains):  # noqa: F811
    return OrganisationDomainSetting(
        tenant_id=state.tenants[tenant],
        version=version,
        verified_domains=domains,
        auto_join=False,
        proof={},
        command_id=uuid4(),
    )


async def test_directory_needs_a_session_and_platform_read(state):  # noqa: F811
    assert (await directory(state, token=None)).status_code == 401
    assert (await directory(state)).status_code == 403


async def test_each_workspace_is_named_for_what_it_is(state):  # noqa: F811
    await grant(state, READ)
    now = datetime.now(UTC)
    with Session(state.engine) as db, db.begin():
        db.add(
            Organisation(
                tenant_id=state.tenants["Suspended"],
                creation_command_id=uuid4(),
                domain_verification_token="f" * 43,
                created_at=now,
            )
        )
        db.flush()
        db.add_all(
            [
                # Verified for the operations staff's email domain: our own company.
                verified(state, "Alpha", 1, ["Example.test"]),
                # The newest setting decides: it was ours once, now only its own domain.
                verified(state, "Suspended", 1, ["example.test"]),
                verified(state, "Suspended", 2, ["customer.test"]),
                ConversationSandboxOrganisation(
                    tenant_id=state.tenants["Inactive"],
                    approved_by_person_id=state.other,
                    approval_reference="AUT-0 fictional sandbox",
                    created_at=now,
                ),
            ]
        )

    response = await directory(state)

    assert response.status_code == 200
    body = PlatformWorkspacesResponse.model_validate_json(response.text)
    assert [
        (item.registered_name, item.name, item.kind, item.status, item.member_count)
        for item in body.workspaces
    ] == [
        ("Alpha", "Alpha", "company", "active", 3),
        ("Suspended", "Suspended", "customer", "suspended", 1),
        # The registered names of Personal and the staff workspace say nothing useful.
        ("Beta", "Personal accounts", "personal", "active", 1),
        ("Inactive", "Inactive", "sandbox", "active", 0),
        ("Other", "AC Operations", "operations", "active", 1),
        ("Deleted", "Deleted", "other", "deleted", 1),
    ]
    assert {item.call_count for item in body.workspaces} == {0}
