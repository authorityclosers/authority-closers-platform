"""Unpaid fictional organisations use only a current pinned seat approval."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from ac_platform.billing.order_models import BillingPeriod
from ac_platform.conversation_intelligence.activation_contract import load_hosted_approval_bundle
from ac_platform.conversation_intelligence.hosted_runtime import PinnedApprovalLoader
from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, OrganisationInvite
from tests.unit.conversation_intelligence.test_activation_contract import _bundle
from tests.unit.conversation_intelligence.test_organisation_seat_exemptions import exemption
from tests.unit.http.test_organisation import call, state  # noqa: F401
from tests.unit.http.test_organisation_invites import identity_cookie, person_call
from tests.unit.http.test_workspaces import OTHER_TOKEN, workspace_state  # noqa: F401


@pytest.fixture
def unpaid(state):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        period = db.scalar(select(BillingPeriod))
        period.period_start = datetime.now(UTC) - timedelta(days=32)
        period.period_end = datetime.now(UTC) - timedelta(days=2)
        member = db.get(Membership, (state.tenant, state.member))
        member.status, member.ended_at = "inactive", datetime.now(UTC)
    return state


def install_approval(state, tmp_path, *, tenant_id=None, **updates):  # noqa: F811
    now = int(datetime.now(UTC).timestamp())
    payload = _bundle(stages=(), issued_at_epoch=now - 60, expires_at_epoch=now + 3600).as_dict()
    payload.update(
        provider_control_tenant_id=str(state.settings.operations_tenant_id),
        organisation_seat_exemptions=[exemption(tenant_id or state.tenant).model_dump(mode="json")],
        **updates,
    )
    bundle = load_hosted_approval_bundle(payload)
    path = tmp_path / "approval.json"
    path.write_bytes(bundle.to_json())
    path.chmod(0o600)
    loader = PinnedApprovalLoader(
        path, bundle.digest, bundle.environment, state.settings.operations_tenant_id
    )
    state.app.state.internal_tester_policy = InternalTesterPolicy(loader, bundle.environment)
    return path


async def test_unpaid_exempt_owner_and_admin_invite_then_verified_people_accept(unpaid, tmp_path):
    install_approval(unpaid, tmp_path)
    assert (await call(unpaid, path="/billing")).json()["paid_seats"] == 0
    billing_reads = []

    @event.listens_for(unpaid.engine, "before_cursor_execute")
    def capture(_connection, _cursor, statement, _parameters, _many, _context):
        if statement.lstrip().upper().startswith("SELECT") and "billing_" in statement:
            billing_reads.append(statement)

    body = {"email": "invited@example.test", "role": "member"}
    invited = await call(unpaid, "POST", "/members", body=body, key=uuid4())
    assert invited.status_code == 200, invited.text
    assert invited.json()["status"] == "invited"
    added = await call(
        unpaid,
        "POST",
        "/members",
        body={"email": "rep@example.test", "role": "member"},
        key=uuid4(),
        token=OTHER_TOKEN,
    )
    assert added.status_code == 200, added.text
    assert added.json()["person_id"] is None
    assert added.json()["status"] == "invited"
    cookie = identity_cookie(unpaid, unpaid.member)
    joined = await person_call(
        unpaid,
        f"/invites/{added.json()['invite_id']}/accept",
        method="POST",
        key=uuid4(),
        token=cookie,
    )
    assert joined.status_code == 200, joined.text
    assert joined.json()["person_id"] == str(unpaid.member)
    person_id = uuid4()
    with Session(unpaid.engine) as db, db.begin():
        db.add(Person(id=person_id, email=body["email"], email_verified_at=datetime.now(UTC)))
    cookie = identity_cookie(unpaid, person_id)
    accepted = await person_call(
        unpaid,
        f"/invites/{invited.json()['invite_id']}/accept",
        method="POST",
        key=uuid4(),
        token=cookie,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["person_id"] == str(person_id)
    assert accepted.json()["status"] == "accepted"
    with Session(unpaid.engine) as db:
        invite = db.get(OrganisationInvite, UUID(invited.json()["invite_id"]))
        assert invite.status == "accepted" and invite.accepted_person_id == person_id
    assert billing_reads == []


@pytest.mark.parametrize(
    "approval",
    ["missing", "none", "unlisted", "wrong_environment", "expired", "future", "error", "tampered"],
)
@pytest.mark.parametrize("email", ["new@example.test", "rep@example.test"])
async def test_unavailable_exemption_preserves_seats_full(unpaid, tmp_path, approval, email):
    updates = {}
    if approval == "wrong_environment":
        updates["environment"] = "staging"
    elif approval == "expired":
        updates.update(issued_at_epoch=1000, expires_at_epoch=2000)
    elif approval == "future":
        now = int(datetime.now(UTC).timestamp())
        updates.update(issued_at_epoch=now + 1000, expires_at_epoch=now + 2000)
    if approval == "none":
        unpaid.app.state.internal_tester_policy = None
    elif approval == "error":
        unpaid.app.state.internal_tester_policy = InternalTesterPolicy(
            Mock(side_effect=RuntimeError("fictional loader failure")), "test"
        )
    elif approval != "missing":
        path = install_approval(
            unpaid, tmp_path, tenant_id=uuid4() if approval == "unlisted" else None, **updates
        )
        if approval == "tampered":
            path.write_bytes(path.read_bytes() + b" ")
    response = await call(
        unpaid, "POST", "/members", body={"email": email, "role": "member"}, key=uuid4()
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "seats_full"
    with Session(unpaid.engine) as db:
        assert db.get(Membership, (unpaid.tenant, unpaid.member)).status == "inactive"
        assert list(db.scalars(select(OrganisationInvite))) == []


async def test_loader_is_checked_again_for_each_addition(unpaid, tmp_path):
    path = install_approval(unpaid, tmp_path)
    response = await call(
        unpaid,
        "POST",
        "/members",
        body={"email": "first@example.test", "role": "member"},
        key=uuid4(),
    )
    assert response.status_code == 200
    path.write_bytes(path.read_bytes() + b" ")
    response = await call(
        unpaid,
        "POST",
        "/members",
        body={"email": "second@example.test", "role": "member"},
        key=uuid4(),
    )
    assert response.status_code == 409 and response.json()["code"] == "seats_full"
