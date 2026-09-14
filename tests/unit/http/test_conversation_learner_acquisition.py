from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import SecretStr

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.acquisition_challenge import UploadChallenge
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.conversation_intelligence.native_runtime import NativeRuntime
from ac_platform.http.auth import AuthenticatedTransaction, AuthenticationRequired
from ac_platform.http.conversation_acquisition_runtime import (
    AcquisitionRuntime,
    install_acquisition_runtime,
)
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext

PUBLIC_TENANT = UUID("206ccee8-a246-433b-b6d3-78eb21592a5c")
OTHER_TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PERSON_ID = UUID("311f4bd2-7b8b-4f45-99f0-a2aed83bc95a")
SESSION_ID = UUID("11111111-1111-4111-8111-111111111111")


class _Database:
    pass


class _SessionScope:
    def __init__(self, database: _Database) -> None:
        self.database = database

    async def __aenter__(self) -> _Database:
        return self.database

    async def __aexit__(self, *_: object) -> None:
        return None


class _Service:
    tenant_id = PUBLIC_TENANT

    def __init__(self, database: _Database) -> None:
        self.database = database
        self.allowance_actors: list[ActorContext] = []

    async def allowance(
        self, *, token: str | None = None, actor: ActorContext | None = None
    ) -> dict[str, int]:
        if actor is not None:
            self.allowance_actors.append(actor)
        return {
            "allowance_seconds": 6000,
            "committed_seconds": 17,
            "available_seconds": 5983,
        }


class _Native(NativeRuntime):
    def inspect(self, source: Path, outdir: Path, *, job_id: UUID, rate: int) -> dict[str, object]:
        raise AssertionError("learner host guard should run before native inspection")


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        public_app_url="https://learner.example.test",
        admin_app_url="https://admin.example.test",
        coach_app_url="https://coach.example.test",
        api_url="https://api.example.test",
        sales_xray_app_url="https://salesxray.example.test",
        public_learner_tenant_id=PUBLIC_TENANT,
        operations_tenant_id=OTHER_TENANT,
        sales_xray_acquisition_enabled=True,
        sales_xray_challenge_site_key="site-key-learner-test",
        sales_xray_acquisition_policy_revision="learner-account-v1",
    )


def _runtime(tmp_path: Path) -> AcquisitionRuntime:
    policy = IntakePolicy(
        budget_scope_id=uuid4(),
        tenant_ids=frozenset({PUBLIC_TENANT}),
        authorization_ref="ref:intake:learner-test",
        retention_ref="ref:retention:learner-test",
    )
    return AcquisitionRuntime(
        intake=ConversationIntakeRuntime(
            policy=policy,
            storage=SimpleNamespace(root=tmp_path / "store", max_bytes=134_217_728),  # type: ignore[arg-type]
            scratch=SimpleNamespace(root=tmp_path / "scratch", max_bytes=134_217_728),  # type: ignore[arg-type]
        ),
        challenge=UploadChallenge(
            secret=SecretStr("challenge-secret-for-unit-test"),
            hostname="salesxray.example.test",
        ),
        preflight=NativeUploadPreflight(_Native()),
        site_key="site-key-learner-test",
        policy_revision="learner-account-v1",
    )


@pytest.mark.asyncio
async def test_learner_mount_requires_public_account_and_keeps_guest_challenge_on_sales(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    database = _Database()
    actor = ActorContext(PERSON_ID, SESSION_ID, PUBLIC_TENANT)
    allowance_actors: list[ActorContext] = []

    async def allowance(
        _self: AcquisitionSessions,
        *,
        token: str | None = None,
        actor: ActorContext | None = None,
    ) -> dict[str, int]:
        if actor is not None:
            allowance_actors.append(actor)
        return {
            "allowance_seconds": 6000,
            "committed_seconds": 17,
            "available_seconds": 5983,
        }

    monkeypatch.setattr(AcquisitionSessions, "allowance", allowance)

    async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        mode = request.headers.get("x-test-auth")
        if mode not in {"valid", "wrong-tenant"}:
            raise AuthenticationRequired("a real account session is required")
        selected = OTHER_TENANT if mode == "wrong-tenant" else actor.tenant_id
        resolved = ResolvedActorContext(
            actor=ActorContext(actor.person_id, actor.session_id, selected),
            membership_role="learner",
            person_revision=1,
            session_revision=1,
        )
        yield AuthenticatedTransaction(
            database,  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            resolved,
            "opaque-session",
        )

    def sessions() -> _SessionScope:
        return _SessionScope(database)

    app = FastAPI()
    register_problem_handlers(app)
    install_acquisition_runtime(
        app,
        settings=settings,
        sessions=sessions,  # type: ignore[arg-type]
        require_actor=require_actor,
        runtime=_runtime(tmp_path),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://learner.example.test"
    ) as learner:
        unauthenticated = await learner.get("/v1/conversation/acquisition/entry")
        assert unauthenticated.status_code == 401

        entry = await learner.get(
            "/v1/conversation/acquisition/entry", headers={"X-Test-Auth": "valid"}
        )
        assert entry.status_code == 200
        assert entry.json() == {
            "enabled": True,
            "site_key": None,
            "challenge_action": None,
            "policy_revision": "learner-account-v1",
            "allowance_seconds": 6000,
            "auth_mode": "account",
        }

        wrong_tenant = await learner.get(
            "/v1/conversation/acquisition/entry", headers={"X-Test-Auth": "wrong-tenant"}
        )
        assert wrong_tenant.status_code == 403

        guest_start = await learner.post(
            "/v1/conversation/acquisition/session",
            json={"challenge_token": "must-not-reach-turnstile"},
            headers={"Origin": "https://learner.example.test"},
        )
        assert guest_start.status_code == 404

        guest_cookie = await learner.get(
            "/v1/conversation/acquisition/session",
            headers={"Cookie": "ac_xray_guest=" + "a" * 43},
        )
        assert guest_cookie.status_code == 401

        account_session = await learner.get(
            "/v1/conversation/acquisition/session",
            headers={"X-Test-Auth": "valid"},
        )
        assert account_session.status_code == 200
        assert account_session.json() == {
            "state": "account",
            "allowance": {
                "allowance_seconds": 6000,
                "committed_seconds": 17,
                "available_seconds": 5983,
            },
        }

        policy = await learner.get(
            "/v1/conversation/acquisition/upload-policy",
            headers={"X-Test-Auth": "valid"},
        )
        assert policy.status_code == 200
        assert policy.json()["max_cost_paise"] == 0
        assert allowance_actors == [actor]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://salesxray.example.test"
    ) as sales:
        entry = await sales.get("/v1/conversation/acquisition/entry")
        assert entry.status_code == 200
        assert entry.json()["site_key"] == "site-key-learner-test"
        assert entry.json()["challenge_action"] == "sales_xray_upload"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://other.example.test"
    ) as wrong_host:
        assert (await wrong_host.get("/v1/conversation/acquisition/entry")).status_code == 404


@pytest.mark.asyncio
async def test_learner_submission_routes_do_not_fall_back_to_guest_cookie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    database = _Database()

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        raise AuthenticationRequired("a real account session is required")
        yield  # pragma: no cover

    def sessions() -> _SessionScope:
        return _SessionScope(database)

    app = FastAPI()
    register_problem_handlers(app)
    runtime = _runtime(tmp_path)
    install_acquisition_runtime(
        app,
        settings=settings,
        sessions=sessions,  # type: ignore[arg-type]
        require_actor=require_actor,
        runtime=runtime,
    )
    monkeypatch.setattr(
        "ac_platform.http.conversation_submissions.account_library",
        lambda *_args, **_kwargs: {"submissions": [], "next_cursor": None},
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://learner.example.test"
    ) as client:
        headers = {"Cookie": "ac_xray_guest=" + "b" * 43}
        for path in (
            "/v1/conversation/acquisition/upload-policy",
            "/v1/conversation/acquisition/submissions",
            f"/v1/conversation/acquisition/submissions/{uuid4()}",
            f"/v1/conversation/acquisition/submissions/{uuid4()}/report",
            f"/v1/conversation/acquisition/submissions/{uuid4()}/source",
        ):
            response = await client.get(path, headers=headers)
            assert response.status_code == 401, (path, response.text)
