from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from ac_platform.conversation_intelligence.activation_contract import (
    InternalTesterApproval,
)
from ac_platform.conversation_intelligence.internal_tester import (
    InternalTesterPolicy,
    account_rate_limit_exemption,
    internal_tester_view,
)
from ac_platform.kernel.authz import ActorContext
from tests.unit.conversation_intelligence.test_activation_contract import _bundle

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
PERSON_ID = UUID("20000000-0000-4000-8000-000000000002")


def _approval(
    email: str,
    *,
    scopes: tuple[str, ...] = (
        "account_minutes",
        "analysis_count",
        "ip_session_issuance",
    ),
) -> InternalTesterApproval:
    return InternalTesterApproval(
        id=uuid4(),
        email=email,
        authorization_ref="ref:approval:tester-20260915",
        scopes=scopes,  # type: ignore[arg-type]
        reason="Approved internal tester exemption",
    )


def _live_bundle(*approvals: InternalTesterApproval):
    now = int(datetime.now(UTC).timestamp())
    return _bundle(
        issued_at_epoch=now - 60,
        expires_at_epoch=now + 3600,
        stages=(),
        internal_tester_accounts=approvals,
    )


class _ScalarDatabase:
    def __init__(self, *values: object) -> None:
        self.values = list(values)

    async def scalar(self, _statement: object) -> object:
        return self.values.pop(0)


def _identity(email: str, *, verified: bool = True) -> tuple[object, object]:
    person = SimpleNamespace(
        status="active",
        email=email,
        email_verified_at=datetime.now(UTC) if verified else None,
    )
    member = SimpleNamespace(status="active", role="learner", ended_at=None)
    return person, member


@pytest.mark.asyncio
async def test_named_accounts_are_exactly_scoped_and_neighbors_stay_bounded() -> None:
    bundle = _live_bundle(
        _approval("admin@authorityclosers.com"),
        _approval("dipak@authorityclosers.com"),
        _approval("suyash@authorityclosers.com"),
    )
    policy = InternalTesterPolicy(lambda: bundle, "test")
    actor = ActorContext(PERSON_ID, uuid4(), TENANT_ID)

    for email in (
        "admin@authorityclosers.com",
        "dipak@authorityclosers.com",
        "suyash@authorityclosers.com",
    ):
        person, member = _identity(email)
        approval = await policy.for_actor(_ScalarDatabase(person, member), actor, "account_minutes")
        assert approval is not None

    for email in (
        "rsuyash123@gmail.com",
        "admin+neighbor@authorityclosers.com",
        "ordinary@example.com",
    ):
        person, member = _identity(email)
        assert (
            await policy.for_actor(_ScalarDatabase(person, member), actor, "account_minutes")
        ) is None


@pytest.mark.asyncio
async def test_unverified_named_identity_does_not_receive_exemption() -> None:
    bundle = _live_bundle(_approval("dipak@authorityclosers.com"))
    person, member = _identity("dipak@authorityclosers.com", verified=False)
    actor = ActorContext(PERSON_ID, uuid4(), TENANT_ID)

    assert (
        await InternalTesterPolicy(lambda: bundle, "test").for_actor(
            _ScalarDatabase(person, member), actor, "analysis_count"
        )
    ) is None


@pytest.mark.asyncio
async def test_processing_membership_does_not_receive_human_tester_exemption() -> None:
    bundle = _live_bundle(_approval("dipak@authorityclosers.com"))
    person, _ = _identity("dipak@authorityclosers.com")
    actor = ActorContext(PERSON_ID, uuid4(), TENANT_ID)
    member = SimpleNamespace(status="active", role="processing", ended_at=None)

    assert (
        await InternalTesterPolicy(lambda: bundle, "test").for_actor(
            _ScalarDatabase(person, member), actor, "analysis_count"
        )
    ) is None


def test_admin_projection_exposes_scopes_without_authorization_references() -> None:
    bundle = _live_bundle(_approval("admin@authorityclosers.com"))

    view = internal_tester_view(bundle)

    assert view["enabled"] is True
    assert view["accounts"] == ["admin@authorityclosers.com"]
    assert view["scopes"] == [
        "account_minutes",
        "analysis_count",
        "ip_session_issuance",
    ]
    assert "authorization_ref" not in view


class _SessionContext:
    def __init__(self, database: _ScalarDatabase) -> None:
        self.database = database

    async def __aenter__(self) -> _SessionContext:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _SessionContext:
        return self

    async def scalar(self, statement: object) -> object:
        return await self.database.scalar(statement)


class _SessionFactory:
    def __init__(self, database: _ScalarDatabase) -> None:
        self.database = database

    def __call__(self) -> _SessionContext:
        return _SessionContext(self.database)


@pytest.mark.asyncio
async def test_ip_exemption_requires_current_named_account_cookie() -> None:
    now = datetime.now(UTC)
    person, member = _identity("suyash@authorityclosers.com")
    session = SimpleNamespace(
        audience="account",
        selected_tenant_id=TENANT_ID,
        person_id=PERSON_ID,
        revoked_at=None,
        expires_at=now + timedelta(minutes=5),
        is_active_at=lambda _now: True,
    )
    bundle = _live_bundle(_approval("suyash@authorityclosers.com"))
    policy = InternalTesterPolicy(lambda: bundle, "test")
    settings = SimpleNamespace(
        session_cookie_name="ac_session",
        session_token_pepper=SecretStr("tester-pepper"),
        public_learner_tenant_id=TENANT_ID,
    )
    scope = {
        "type": "http",
        "headers": [(b"cookie", b"ac_session=" + b"a" * 43)],
    }

    allowed = await account_rate_limit_exemption(
        scope,
        "conversation-acquisition-session",
        settings=settings,
        sessions=_SessionFactory(_ScalarDatabase(session, person, member)),  # type: ignore[arg-type]
        policy=policy,
    )
    assert allowed is True

    neighbor, neighbor_member = _identity("ordinary@example.com")
    bounded = await account_rate_limit_exemption(
        scope,
        "conversation-acquisition-session",
        settings=settings,
        sessions=_SessionFactory(_ScalarDatabase(session, neighbor, neighbor_member)),  # type: ignore[arg-type]
        policy=policy,
    )
    assert bounded is False
