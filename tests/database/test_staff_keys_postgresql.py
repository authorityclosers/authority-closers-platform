"""Staff keys on PostgreSQL, end to end through auth's require_actor.

The control account makes a key right after signing in; the key reaches only the settings
registry's routes on the Admin host, with the scope each needs; and it stops working when
revoked, when expired, when the person is no longer a control account, on another host,
with a cookie, or for anything outside the registry. Fictional rows only.
"""

from __future__ import annotations

import dataclasses
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import func, select, update
from starlette.requests import Request

import ac_platform.admin_settings.staff_keys as staff_keys_module
from ac_platform.admin_settings.http import install_admin_settings_http
from ac_platform.admin_settings.models import AdminStaffKey
from ac_platform.admin_settings.staff_keys import CREATED, REVOKED, USED, StaffKeys
from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.application import (
    ConversationDenied,
    ConversationError,
)
from ac_platform.http.auth import (
    AdminSurfaceRequired,
    AuthenticationRequired,
    install_identity_http,
)
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Session
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_reviews_postgresql import ReviewCase, run
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)
from tests.unit.http.test_conversation_learner_acquisition import _settings


def _settings_for(case: ReviewCase) -> Any:
    return _settings().model_copy(update={"operations_tenant_id": case.operations_tenant_id})


class Harness:
    def __init__(self, case: ReviewCase) -> None:
        self.case = case
        self.settings = _settings_for(case)
        self.app = FastAPI()
        self.require_actor = install_identity_http(
            self.app, settings=self.settings, sessions=case.sessions
        )
        install_admin_settings_http(
            self.app, settings=self.settings, require_actor=self.require_actor
        )
        self.host = self.settings.admin_app_url.host

    def identity(self, database: Any) -> AsyncIdentityApplication:
        pepper = self.settings.session_token_pepper.get_secret_value()
        return AsyncIdentityApplication(database, token_pepper=pepper)

    async def make(self, scopes: list[str], name: str = "CLI") -> dict[str, Any]:
        async with self.case.sessions() as database, database.begin():
            return await StaffKeys(database, self.settings).create(
                self.case.admin_actor,
                self.identity(database),
                name=name,
                scopes=scopes,
                now=datetime.now(UTC),
            )

    async def call(
        self, method: str, path: str, key: str, *, host: str | None = None, cookie: str = ""
    ) -> Request:
        headers = [(b"authorization", f"Bearer {key}".encode())]
        if cookie:
            headers.append((b"cookie", cookie.encode()))
        request = Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "query_string": b"",
                "scheme": "https",
                "server": (host or self.host, 443),
                "headers": headers,
                "app": self.app,
            }
        )
        stream = self.require_actor(request)
        await stream.__anext__()
        with suppress(StopAsyncIteration):
            await stream.__anext__()  # finish the transaction: commit
        return request


async def _retire_earlier_keys(case: ReviewCase) -> None:
    """The test database outlives one test: start each with no active key for this person."""
    now = datetime.now(UTC)
    async with case.sessions() as database, database.begin():
        await database.execute(
            update(AdminStaffKey)
            .where(
                AdminStaffKey.person_id == case.admin_actor.person_id,
                AdminStaffKey.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_by_person_id=case.admin_actor.person_id)
        )


async def exercise(case: ReviewCase, monkeypatch: pytest.MonkeyPatch) -> None:
    await _retire_earlier_keys(case)
    harness = Harness(case)
    reader = await harness.make(["settings:read"], "Reader")
    writer = await harness.make(["settings:read", "settings:write"], "Writer")
    assert reader["key"].startswith("ac_dev_") and reader["prefix"] in reader["key"]
    assert reader["state"] == "active" and "key" not in (await _mine(harness))["keys"][0]

    # At most two active keys a person.
    with pytest.raises(ConversationError, match="2 active keys"):
        await harness.make(["settings:read"], "Third")

    # A key reads the registry; only a settings:write key reaches a change route.
    request = await harness.call("GET", "/v1/admin/settings", reader["key"])
    assert request.state.staff_key is True
    with pytest.raises(HTTPException, match="settings:write") as refused:
        await harness.call("POST", "/v1/admin/conversation/execution", reader["key"])
    assert refused.value.status_code == 403
    await harness.call("POST", "/v1/admin/conversation/execution", writer["key"])

    # Anything outside the registry stays in the browser: billing-adjacent, keys, others.
    for method, path in (
        ("POST", "/v1/admin/conversation/budget/settings"),
        ("GET", "/v1/admin/staff-keys"),
        ("POST", "/v1/admin/staff-keys"),
        ("GET", "/v1/admin/integrations"),
        ("GET", "/v1/admin/conversation/calls"),
    ):
        with pytest.raises(HTTPException) as blocked:
            await harness.call(method, path, writer["key"])
        assert blocked.value.status_code == 403, path

    # Never on another host, never with a session cookie.
    with pytest.raises(AdminSurfaceRequired):
        await harness.call("GET", "/v1/admin/settings", reader["key"], host="evil.example")
    cookie = f"{harness.settings.session_cookie_name}=" + "c" * 43
    with pytest.raises(AuthenticationRequired, match="not both"):
        await harness.call("GET", "/v1/admin/settings", reader["key"], cookie=cookie)

    # Rate-limited per key.
    monkeypatch.setattr(
        staff_keys_module,
        "RULE",
        dataclasses.replace(staff_keys_module.RULE, capacity=1, refill_seconds=3600.0),
    )
    harness.app.state.staff_keys = staff_keys_module.StaffKeyGuard(harness.settings)
    await harness.call("GET", "/v1/admin/settings", reader["key"])
    with pytest.raises(HTTPException) as limited:
        await harness.call("GET", "/v1/admin/settings", reader["key"])
    assert limited.value.status_code == 429
    harness.app.state.staff_keys = staff_keys_module.StaffKeyGuard(harness.settings)
    monkeypatch.undo()
    harness.app.state.staff_keys = staff_keys_module.StaffKeyGuard(harness.settings)

    async with case.sessions() as database:
        used = (await database.get(AdminStaffKey, _id(writer))).last_used_at  # type: ignore[union-attr]
        actions = (
            await database.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.action.in_((CREATED, REVOKED, USED)),
                    AuditEvent.resource_id.in_((reader["id"], writer["id"])),
                )
            )
        ).all()
    assert used is not None
    assert sorted(actions) == sorted([CREATED, CREATED, USED])

    # Expired: refused.
    async with case.sessions() as database, database.begin():
        await database.execute(
            update(AdminStaffKey)
            .where(AdminStaffKey.id == _id(reader))
            .values(
                created_at=datetime.now(UTC) - timedelta(days=31),
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
    with pytest.raises(AuthenticationRequired, match="expired"):
        await harness.call("GET", "/v1/admin/settings", reader["key"])

    # Revoked: refused, and its session ends with it.
    async with case.sessions() as database, database.begin():
        revoked = await StaffKeys(database, harness.settings).revoke(
            case.admin_actor, _id(writer), now=datetime.now(UTC)
        )
    assert revoked["state"] == "revoked"
    with pytest.raises(AuthenticationRequired, match="revoked"):
        await harness.call("GET", "/v1/admin/settings", writer["key"])
    async with case.sessions() as database:
        row = await database.get(AdminStaffKey, _id(writer))
        assert row is not None
        assert await database.scalar(select(Session.revoked_at).where(Session.id == row.session_id))

    # A fresh key, then the person is no longer an owner or admin there: refused.
    fresh = await harness.make(["settings:read"], "Fresh")
    mine = (
        Membership.tenant_id == case.operations_tenant_id,
        Membership.person_id == case.admin_actor.person_id,
    )
    async with case.sessions() as database, database.begin():
        role = await database.scalar(select(Membership.role).where(*mine))
        await database.execute(update(Membership).where(*mine).values(role="member"))
    try:
        with pytest.raises(HTTPException) as demoted:
            await harness.call("GET", "/v1/admin/settings", fresh["key"])
        assert demoted.value.status_code == 403
    finally:
        # The test database outlives this test: give the role back.
        async with case.sessions() as database, database.begin():
            await database.execute(update(Membership).where(*mine).values(role=role))


async def _mine(harness: Harness) -> dict[str, Any]:
    async with harness.case.sessions() as database, database.begin():
        return await StaffKeys(database, harness.settings).mine(
            harness.case.admin_actor, now=datetime.now(UTC)
        )


def _id(view: dict[str, Any]) -> Any:
    from uuid import UUID

    return UUID(view["id"])


async def _count(case: ReviewCase) -> int:
    async with case.sessions() as database:
        return int(
            await database.scalar(
                select(func.count())
                .select_from(AdminStaffKey)
                .where(AdminStaffKey.person_id == case.admin_actor.person_id)
            )
            or 0
        )


async def stale_sign_in(case: ReviewCase) -> None:
    await _retire_earlier_keys(case)
    harness = Harness(case)
    before = await _count(case)
    async with case.sessions() as database, database.begin():
        await database.execute(
            update(Session)
            .where(Session.id == case.admin_actor.session_id)
            .values(created_at=datetime.now(UTC) - timedelta(minutes=20))
        )
    with pytest.raises(ConversationDenied, match="Sign in again"):
        await harness.make(["settings:read"])
    assert await _count(case) == before


def test_staff_keys_reach_only_settings_and_stop_when_they_should(
    review_case: ReviewCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(exercise(review_case, monkeypatch))


def test_a_key_needs_a_sign_in_within_ten_minutes(review_case: ReviewCase) -> None:
    run(stale_sign_in(review_case))
