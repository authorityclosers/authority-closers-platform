"""Sales Xray serves the selected tenant on PostgreSQL (AUT-436).

Personal and an organisation approved in the hosted bundle are served; the
operations tenant and an organisation outside the list get 403 on every
route. Personal and organisation calls are invisible to each other. An
organisation starts with 0 trial seconds and gains minutes only through an
Admin grant or the internal-tester exemption.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.ledger import BillingLedger
from ac_platform.conversation_intelligence.acquisition_challenge import UploadChallenge
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.activation_contract import InternalTesterApproval
from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
from ac_platform.conversation_intelligence.minute_account_admin import (
    EligibleLearnerUnavailable,
    require_eligible_learner,
)
from ac_platform.conversation_intelligence.minute_account_targets import (
    resolve_public_learner_target,
)
from ac_platform.conversation_intelligence.sales_xray_tenants import (
    CLAIM_PERSONAL_ONLY_MESSAGE,
    WORKSPACE_UNAVAILABLE_MESSAGE,
)
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation_acquisition import install_acquisition_http
from ac_platform.http.conversation_submissions import install_submission_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_authority_postgresql import _bundle
from tests.database.test_conversation_guest_ownership_postgresql import _provision
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _setup,
    _upload_for_read_test,
    _wav_one_second_48k,
)


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def _token_hash(token: str, pepper: str) -> bytes:
    return hmac.new(pepper.encode("utf-8"), token.encode("ascii"), hashlib.sha256).digest()


async def _workspace_app(postgres_harness: Any, tmp_path: Any) -> SimpleNamespace:
    """Personal plus one approved and one unlisted organisation for the same person."""

    setup = await _setup(postgres_harness, tmp_path, separate_operations=True)
    state, settings = setup.state, setup.settings
    organisation = await seed(setup.engine, role="owner")
    unlisted = await seed(setup.engine, role="owner")
    # An approved organisation owns its processing principal (A2a); the
    # unlisted one has none, which is beside the point: it is refused earlier.
    await _provision(setup.engine, organisation)
    pepper = settings.session_token_pepper.get_secret_value()
    tokens = {
        name: secrets.token_urlsafe(32) for name in ("organisation", "unlisted", "operations")
    }
    email = f"member-{state.person_id.hex}@example.test"
    async with setup.sessions() as db, db.begin():
        await db.execute(update(Person).where(Person.id == state.person_id).values(email=email))
        for name, tenant in (("organisation", organisation), ("unlisted", unlisted)):
            db.add(Membership(tenant_id=tenant.tenant_id, person_id=state.person_id, role="member"))
            await db.flush()
            db.add(
                IdentitySession(
                    id=uuid4(),
                    person_id=state.person_id,
                    selected_tenant_id=tenant.tenant_id,
                    token_hash=_token_hash(tokens[name], pepper),
                    expires_at=state.now + timedelta(days=1),
                )
            )
        # The operations tenant's own seeded session (the control tenant of _setup).
        await db.execute(
            update(IdentitySession)
            .where(IdentitySession.selected_tenant_id == settings.operations_tenant_id)
            .values(token_hash=_token_hash(tokens["operations"], pepper))
        )
    finite_bundle = _bundle(state, "0" * 64, "a" * 64, now_epoch=int(state.now.timestamp()))
    bundle_box = {"bundle": finite_bundle}
    tester_policy = InternalTesterPolicy(lambda: bundle_box["bundle"], "test")

    def factory(db: AsyncSession, tenant_id: Any) -> AcquisitionSessions:
        return AcquisitionSessions(
            db,
            tenant_id=tenant_id,
            policy_revision="guest-processing-v1",
            clock=lambda: setup.clock[0],
            tester_policy=tester_policy,
            operations_tenant_id=settings.operations_tenant_id,
            trial_enabled=tenant_id == state.tenant_id,
        )

    runtime = replace(
        setup.runtime,
        policy=replace(
            setup.runtime.policy,
            tenant_ids=frozenset({state.tenant_id, organisation.tenant_id}),
        ),
    )
    app = FastAPI()
    register_problem_handlers(app)
    require_actor = install_identity_http(app, settings=settings, sessions=setup.sessions)
    install_submission_http(
        app,
        settings=settings,
        sessions=setup.sessions,
        require_actor=require_actor,
        factory=factory,
        runtime=runtime,
        preflight=NativeUploadPreflight(setup.native),
    )
    install_acquisition_http(
        app,
        settings=settings,
        sessions=setup.sessions,
        require_actor=require_actor,
        factory=factory,
        challenge=UploadChallenge(
            secret=settings.session_token_pepper, hostname="salesxray.example.test"
        ),
        intake=runtime,
    )
    return SimpleNamespace(
        setup=setup,
        app=app,
        organisation=organisation,
        unlisted=unlisted,
        tokens=tokens,
        email=email,
        bundle_box=bundle_box,
        finite_bundle=finite_bundle,
        tester_policy=tester_policy,
    )


def test_sales_xray_serves_personal_and_approved_organisation_only(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        workspace = await _workspace_app(postgres_harness, tmp_path)
        setup, settings = workspace.setup, workspace.setup.settings
        state, organisation = setup.state, workspace.organisation
        cookie = settings.session_cookie_name
        data = _wav_one_second_48k()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=workspace.app), base_url=ORIGIN
            ) as client:

                def select_workspace(token: str) -> None:
                    client.cookies.clear()
                    client.cookies.set(cookie, token)

                # Personal is unchanged: the trial, an upload and the library.
                select_workspace(setup.token)
                personal = await client.get(PREFIX + "/session")
                assert personal.status_code == 200, personal.text
                assert personal.json()["state"] == "account"
                assert personal.json()["allowance"]["allowance_seconds"] == 3600
                personal_path, personal_id = await _upload_for_read_test(setup, client)

                # The organisation starts at 0 s and admits no upload.
                select_workspace(workspace.tokens["organisation"])
                organisation_session = await client.get(PREFIX + "/session")
                assert organisation_session.status_code == 200, organisation_session.text
                assert organisation_session.json() == {
                    "state": "account",
                    "allowance": {
                        "allowance_seconds": 0,
                        "committed_seconds": 0,
                        "available_seconds": 0,
                    },
                }
                refused = await client.put(
                    f"{PREFIX}/submissions/{uuid4()}/source",
                    content=data,
                    headers=await _headers(client, data),
                )
                # The same refusal an exhausted Personal account gets.
                assert refused.status_code == 409, refused.text
                assert refused.json()["detail"] == "Your current free call allowance has been used."

                # An Admin grant applies in the organisation: the eligibility gate
                # and target lookup accept the member role, and the ledger lot the
                # grant route writes shows up in the organisation allowance.
                async with setup.sessions() as db, db.begin():
                    await require_eligible_learner(
                        db,
                        tenant_id=organisation.tenant_id,
                        person_id=state.person_id,
                        operations_tenant_id=settings.operations_tenant_id,
                    )
                    target, lookup_kind = await resolve_public_learner_target(
                        db, tenant_id=organisation.tenant_id, query=workspace.email
                    )
                    assert lookup_kind == "email" and target is not None
                    assert (target.tenant_id, target.person_id) == (
                        organisation.tenant_id,
                        state.person_id,
                    )
                    with pytest.raises(EligibleLearnerUnavailable):
                        await require_eligible_learner(
                            db,
                            tenant_id=organisation.tenant_id,
                            person_id=uuid4(),
                            operations_tenant_id=settings.operations_tenant_id,
                        )
                    ledger = BillingLedger(
                        db,
                        clock=lambda: setup.clock[0],
                        operations_tenant_id=settings.operations_tenant_id,
                    )
                    account = await ledger.personal_account(
                        tenant_id=organisation.tenant_id, person_id=state.person_id, create=True
                    )
                    assert account is not None
                    await ledger.write_lot(
                        account=account,
                        kind="grant",
                        seconds=600,
                        valid_from=setup.clock[0],
                        source_ref="test:organisation-admin-grant",
                        actor_type="person",
                        actor_person_id=organisation.person_id,
                        reason="Synthetic Admin grant",
                    )
                granted = await client.get(PREFIX + "/session")
                assert granted.json()["allowance"] == {
                    "allowance_seconds": 600,
                    "committed_seconds": 0,
                    "available_seconds": 600,
                }

                # Upload, library, read and delete work inside the organisation,
                # and the two workspaces cannot see each other's calls.
                organisation_path, organisation_id = await _upload_for_read_test(setup, client)
                library = await client.get(PREFIX + "/submissions")
                assert library.status_code == 200, library.text
                assert [item["submission_id"] for item in library.json()["submissions"]] == [
                    str(organisation_id)
                ]
                assert (await client.get(organisation_path)).status_code == 200
                assert (await client.get(personal_path)).status_code == 404
                select_workspace(setup.token)
                library = await client.get(PREFIX + "/submissions")
                assert [item["submission_id"] for item in library.json()["submissions"]] == [
                    str(personal_id)
                ]
                assert (await client.get(personal_path)).status_code == 200
                assert (await client.get(organisation_path)).status_code == 404
                select_workspace(workspace.tokens["organisation"])
                deleted = await client.delete(
                    organisation_path,
                    headers={"Origin": ORIGIN, "Idempotency-Key": "organisation-delete"},
                )
                assert deleted.status_code == 202, deleted.text

                # A guest upload is claimed from Personal only.
                client.cookies.set("ac_xray_guest", setup.guest.token)
                claim_required = await client.get(PREFIX + "/session")
                assert claim_required.status_code == 200, claim_required.text
                assert claim_required.json()["state"] == "claim_required"
                claim = await client.post(PREFIX + "/claim", headers={"Origin": ORIGIN})
                assert claim.status_code == 409, claim.text
                assert claim.json()["detail"] == CLAIM_PERSONAL_ONLY_MESSAGE

                # The internal-tester exemption applies to the organisation member.
                approval = InternalTesterApproval(
                    id=uuid4(),
                    email=workspace.email,
                    authorization_ref="ref:approval:organisation-tester",
                    scopes=("account_minutes",),
                    reason="Approved internal tester exemption",
                )
                workspace.bundle_box["bundle"] = workspace.finite_bundle.model_copy(
                    update={"internal_tester_accounts": (approval,)}
                )
                select_workspace(workspace.tokens["organisation"])
                unlimited = await client.get(PREFIX + "/session")
                assert unlimited.json()["allowance"]["unlimited"] is True
                async with setup.sessions() as db, db.begin():
                    exemption = await workspace.tester_policy.for_learner_account(
                        db, tenant_id=organisation.tenant_id, person_id=state.person_id
                    )
                    assert exemption is not None and exemption.email == workspace.email

                # The operations tenant and an unlisted organisation: 403 everywhere.
                # Real upload headers: the header check runs before authentication.
                upload_headers = await _headers(client, data)
                for name in ("operations", "unlisted"):
                    select_workspace(workspace.tokens[name])
                    client.cookies.set("ac_xray_guest", setup.guest.token)
                    attempts: list[tuple[str, str, dict[str, Any]]] = [
                        ("GET", PREFIX + "/session", {}),
                        ("GET", "/v1/me/plan", {}),
                        ("GET", "/v1/me/usage", {}),
                        # /upload-policy is public on the sales host: guests read
                        # the consent text before signing in, so it is not listed.
                        ("GET", PREFIX + "/submissions", {}),
                        ("GET", PREFIX + "/submissions/summary", {}),
                        ("GET", PREFIX + "/activity", {}),
                        ("GET", personal_path, {}),
                        ("GET", personal_path + "/report", {}),
                        (
                            "PUT",
                            f"{PREFIX}/submissions/{uuid4()}/source",
                            {"content": data, "headers": upload_headers},
                        ),
                        (
                            "DELETE",
                            personal_path,
                            {"headers": {"Origin": ORIGIN, "Idempotency-Key": f"{name}-delete"}},
                        ),
                        ("POST", PREFIX + "/claim", {"headers": {"Origin": ORIGIN}}),
                    ]
                    for method, path, kwargs in attempts:
                        response = await client.request(method, path, **kwargs)
                        assert response.status_code == 403, (name, method, path, response.text)
                        assert response.json()["detail"] == WORKSPACE_UNAVAILABLE_MESSAGE
                select_workspace(setup.token)
                assert (await client.get(personal_path)).status_code == 200
        finally:
            await setup.engine.dispose()

    run(exercise())
