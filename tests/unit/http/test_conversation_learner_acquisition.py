from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import SecretStr

import ac_platform.http.conversation_acquisition_runtime as acquisition_runtime_module
from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.acquisition_challenge import UploadChallenge
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    AnalysisSettings,
)
from ac_platform.conversation_intelligence.application import ConversationNotFound
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.conversation_intelligence.native_runtime import NativeRuntime
from ac_platform.conversation_intelligence.sales_xray_tenants import (
    CLAIM_PERSONAL_ONLY_MESSAGE,
    WORKSPACE_UNAVAILABLE_MESSAGE,
)
from ac_platform.http.auth import AuthenticatedTransaction, AuthenticationRequired
from ac_platform.http.conversation_acquisition_runtime import (
    AcquisitionRuntime,
    install_acquisition_runtime,
)
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.conversation_submissions import install_submission_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext

PUBLIC_TENANT = UUID("206ccee8-a246-433b-b6d3-78eb21592a5c")
OTHER_TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PERSON_ID = UUID("311f4bd2-7b8b-4f45-99f0-a2aed83bc95a")
SESSION_ID = UUID("11111111-1111-4111-8111-111111111111")


@pytest.mark.parametrize("environment", ["development", "staging", "production", "local", "test"])
@pytest.mark.parametrize("socket_kind", ["missing", "regular_file"])
def test_acquisition_requires_hosted_native_socket(tmp_path, monkeypatch, environment, socket_kind):
    socket_path = tmp_path.parent / f"native-{uuid4().hex[:8]}.sock"
    if socket_kind == "regular_file":
        socket_path.touch(mode=0o600)
    settings = _settings().model_copy(
        update={
            "environment": environment,
            "sales_xray_native_socket_path": str(socket_path),
            "sales_xray_native_image_ref": "sha256:" + "c" * 64,
            "sales_xray_challenge_secret_file": str(tmp_path / "fictional-challenge"),
        }
    )
    monkeypatch.setattr(
        acquisition_runtime_module, "_challenge_secret", lambda _: SecretStr("fictional-challenge")
    )
    intake = _runtime(tmp_path).intake
    if environment in {"local", "test"}:
        assert acquisition_runtime_module.compose_acquisition(settings, intake) is not None
    else:
        with pytest.raises(ValueError, match="^acquisition_native_helper_unavailable$"):
            acquisition_runtime_module.compose_acquisition(settings, intake)


@pytest.mark.parametrize("environment", ["development", "staging", "production", "local", "test"])
def test_submission_install_requires_hosted_native_socket(tmp_path, environment):
    runtime = _runtime(tmp_path)
    application = FastAPI()
    kwargs = dict(
        application=application,
        settings=_settings().model_copy(update={"environment": environment}),
        sessions=None,
        require_actor=None,
        factory=None,
        runtime=runtime.intake,
        preflight=runtime.preflight,
    )
    if environment in {"local", "test"}:
        install_submission_http(**kwargs)
        assert "/v1/conversation/acquisition/submissions" in application.openapi()["paths"]
    else:
        with pytest.raises(ValueError, match="Hosted source preflight requires the bounded native"):
            install_submission_http(**kwargs)


class _Database:
    def begin(self) -> _TransactionScope:
        return _TransactionScope(self)


class _TransactionScope:
    def __init__(self, database: _Database) -> None:
        self.database = database

    async def __aenter__(self) -> _Database:
        return self.database

    async def __aexit__(self, *_: object) -> None:
        return None


class _SessionScope:
    def __init__(self, database: _Database) -> None:
        self.database = database

    async def __aenter__(self) -> _Database:
        return self.database

    async def __aexit__(self, *_: object) -> None:
        return None


class _Service:
    def __init__(self, database: _Database, tenant_id: UUID = PUBLIC_TENANT) -> None:
        self.database, self.tenant_id = database, tenant_id
        self.allowance_actors: list[ActorContext] = []
        self.allowance_lock_modes: list[bool] = []

    async def allowance(
        self,
        *,
        token: str | None = None,
        actor: ActorContext | None = None,
        shared_identity_locks: bool = False,
    ) -> dict[str, int]:
        self.allowance_lock_modes.append(shared_identity_locks)
        if actor is not None:
            self.allowance_actors.append(actor)
        return {
            "allowance_seconds": 3600,
            "committed_seconds": 17,
            "available_seconds": 3583,
        }


class _Native(NativeRuntime):
    def inspect(self, source: Path, outdir: Path, *, job_id: UUID, rate: int) -> dict[str, object]:
        raise AssertionError("learner host guard should run before native inspection")

    def validate_source(
        self, source: Path, outdir: Path, *, job_id: UUID, rate: int
    ) -> dict[str, object]:
        raise AssertionError("learner host guard should run before native validation")


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
    selected_settings = DEFAULT_ANALYSIS_SETTINGS

    async def current_settings(_database: object, _tenant_id: UUID):
        return None, selected_settings

    monkeypatch.setattr(acquisition_runtime_module, "latest_analysis_settings", current_settings)
    actor = ActorContext(PERSON_ID, SESSION_ID, PUBLIC_TENANT)
    allowance_actors: list[ActorContext] = []
    allowance_lock_modes: list[bool] = []

    async def allowance(
        _self: AcquisitionSessions,
        *,
        token: str | None = None,
        actor: ActorContext | None = None,
        shared_identity_locks: bool = False,
    ) -> dict[str, int]:
        allowance_lock_modes.append(shared_identity_locks)
        if actor is not None:
            allowance_actors.append(actor)
        return {
            "allowance_seconds": 3600,
            "committed_seconds": 17,
            "available_seconds": 3583,
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
            "allowance_seconds": 3600,
            "auth_mode": "account",
            "report_languages": ["en"],
            "report_language_default": "en",
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
                "allowance_seconds": 3600,
                "committed_seconds": 17,
                "available_seconds": 3583,
            },
        }

        policy = await learner.get(
            "/v1/conversation/acquisition/upload-policy",
            headers={"X-Test-Auth": "valid"},
        )
        assert policy.status_code == 200
        assert policy.json()["max_cost_paise"] == 0
        assert allowance_actors == [actor]
        assert allowance_lock_modes == [True]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://salesxray.example.test"
    ) as sales:
        selected_settings = AnalysisSettings.model_validate(
            {
                **DEFAULT_ANALYSIS_SETTINGS.effective_values(),
                "c5_coaching_prompt_revision": "coaching-v4",
                "report_language_default": "mr-Deva+en",
            }
        )
        entry = await sales.get("/v1/conversation/acquisition/entry")
        assert entry.status_code == 200
        assert entry.json()["site_key"] == "site-key-learner-test"
        assert entry.json()["challenge_action"] == "sales_xray_upload"
        assert entry.json()["report_languages"] == ["en", "hi-Deva+en", "mr-Deva+en"]
        assert entry.json()["report_language_default"] == "mr-Deva+en"
        existing_guest = await sales.post(
            "/v1/conversation/acquisition/session",
            json={"challenge_token": "already-has-a-guest-session"},
            headers={"Cookie": "ac_xray_guest=" + "a" * 43},
        )
        assert existing_guest.status_code == 200
        assert allowance_lock_modes == [True, False]

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "suffix", ["", "/report", "/report.docx", "/transcript", "/waveform", "/source"]
)
async def test_unavailable_learner_submission_returns_private_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    database = _Database()
    unwound: list[bool] = []

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        try:
            yield AuthenticatedTransaction(
                database,  # type: ignore[arg-type]
                SimpleNamespace(),  # type: ignore[arg-type]
                ResolvedActorContext(
                    actor=ActorContext(PERSON_ID, SESSION_ID, PUBLIC_TENANT),
                    membership_role="learner",
                    person_revision=1,
                    session_revision=1,
                ),
                "opaque-session",
            )
        finally:
            unwound.append(True)

    async def unavailable(_self: GuestOwnership, *_args: object, **_kwargs: object) -> None:
        # Expired retention, deletion and unavailable ownership all use this
        # non-disclosing domain denial; no report or source may be returned.
        raise ConversationNotFound("This upload is unavailable.")

    monkeypatch.setattr(GuestOwnership, "require_submission_owner", unavailable)
    app = FastAPI()
    register_problem_handlers(app)
    install_acquisition_runtime(
        app,
        settings=_settings(),
        sessions=lambda: _SessionScope(database),  # type: ignore[arg-type]
        require_actor=require_actor,
        runtime=_runtime(tmp_path),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://learner.example.test",
    ) as client:
        response = await client.get(f"/v1/conversation/acquisition/submissions/{uuid4()}{suffix}")
    assert response.status_code == 404
    assert "This upload is unavailable." in response.text
    assert "no-store" in response.headers["cache-control"]
    assert unwound == [True]


ORGANISATION_TENANT = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
UNLISTED_TENANT = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
_SELECTED_TENANTS = {
    "personal": PUBLIC_TENANT,
    "organisation": ORGANISATION_TENANT,
    "operations": OTHER_TENANT,
    "unlisted": UNLISTED_TENANT,
}


@pytest.mark.asyncio
async def test_routes_serve_the_selected_workspace_and_refuse_operations_and_unlisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AUT-436: Personal and an approved organisation are served; nothing else is."""

    settings = _settings()
    database = _Database()

    async def current_settings(_database: object, _tenant_id: UUID):
        return None, DEFAULT_ANALYSIS_SETTINGS

    monkeypatch.setattr(acquisition_runtime_module, "latest_analysis_settings", current_settings)
    services: list[tuple[UUID, bool, str | None]] = []

    async def allowance(
        _self: AcquisitionSessions,
        *,
        token: str | None = None,
        actor: ActorContext | None = None,
        shared_identity_locks: bool = False,
    ) -> dict[str, int]:
        services.append((_self.tenant_id, _self.trial_enabled, token))
        return {"allowance_seconds": 0, "committed_seconds": 0, "available_seconds": 0}

    monkeypatch.setattr(AcquisitionSessions, "allowance", allowance)
    summaries: list[UUID] = []

    async def summary(ownership: GuestOwnership, actor: ActorContext, **_kwargs: object):
        summaries.append(ownership.tenant_id)
        return {"total": 0, "processing": 0, "completed": 0, "needs_attention": 0}

    monkeypatch.setattr(
        "ac_platform.http.conversation_submissions.account_library_summary", summary
    )

    async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        selected = _SELECTED_TENANTS.get(request.headers.get("x-test-tenant", ""))
        if selected is None:
            raise AuthenticationRequired("a real account session is required")
        yield AuthenticatedTransaction(
            database,  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            ResolvedActorContext(
                actor=ActorContext(PERSON_ID, SESSION_ID, selected),
                membership_role="learner" if selected == PUBLIC_TENANT else "member",
                person_revision=1,
                session_revision=1,
            ),
            "opaque-session",
        )

    def sessions() -> _SessionScope:
        return _SessionScope(database)

    runtime = _runtime(tmp_path)
    runtime = replace(
        runtime,
        intake=replace(
            runtime.intake,
            policy=replace(
                runtime.intake.policy,
                tenant_ids=frozenset({PUBLIC_TENANT, ORGANISATION_TENANT, OTHER_TENANT}),
            ),
        ),
    )
    app = FastAPI()
    register_problem_handlers(app)
    install_acquisition_runtime(
        app,
        settings=settings,
        sessions=sessions,  # type: ignore[arg-type]
        require_actor=require_actor,
        runtime=runtime,
    )
    prefix = "/v1/conversation/acquisition"
    reads = (
        prefix + "/entry",
        prefix + "/session",
        prefix + "/submissions/summary",
        "/v1/me/plan",
        "/v1/me/usage",
    )
    monkeypatch.setattr(
        "ac_platform.http.conversation_acquisition.account_usage",
        AsyncMock(return_value={"calls": [], "earlier_seconds": 0, "truncated": False}),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://learner.example.test"
    ) as learner:
        for path in reads:
            served = await learner.get(path, headers={"X-Test-Tenant": "organisation"})
            assert served.status_code == 200, (path, served.text)
            for name in ("operations", "unlisted"):
                refused = await learner.get(path, headers={"X-Test-Tenant": name})
                assert refused.status_code == 403, (path, name, refused.text)
                assert refused.json()["detail"] == WORKSPACE_UNAVAILABLE_MESSAGE
        # The organisation service carries the selected tenant and no trial.
        assert services and set(services) == {(ORGANISATION_TENANT, False, None)}
        assert summaries == [ORGANISATION_TENANT]
        personal = await learner.get(prefix + "/session", headers={"X-Test-Tenant": "personal"})
        assert personal.status_code == 200
        assert services[-1] == (PUBLIC_TENANT, True, None)

    services.clear()
    summaries.clear()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://salesxray.example.test"
    ) as sales:
        sales.cookies.set(settings.session_cookie_name, "s" * 43)
        organisation = {"X-Test-Tenant": "organisation"}
        session = await sales.get(prefix + "/session", headers=organisation)
        assert session.status_code == 200 and session.json()["state"] == "account"
        assert services[-1] == (ORGANISATION_TENANT, False, None)
        summary_response = await sales.get(prefix + "/submissions/summary", headers=organisation)
        assert summary_response.status_code == 200 and summaries == [ORGANISATION_TENANT]
        for name in ("operations", "unlisted"):
            refused = await sales.get(prefix + "/session", headers={"X-Test-Tenant": name})
            assert refused.status_code == 403, refused.text
            assert refused.json()["detail"] == WORKSPACE_UNAVAILABLE_MESSAGE

        # A guest cookie belongs to Personal: the organisation session reports the
        # unclaimed visitor (checked on the Personal service) and the claim says
        # how to proceed instead of moving the upload into the organisation.
        sales.cookies.set("ac_xray_guest", "a" * 43)
        claim_required = await sales.get(prefix + "/session", headers=organisation)
        assert claim_required.status_code == 200
        assert claim_required.json()["state"] == "claim_required"
        assert services[-1] == (PUBLIC_TENANT, True, "a" * 43)
        claim = await sales.post(
            prefix + "/claim",
            headers={**organisation, "Origin": "https://salesxray.example.test"},
        )
        assert claim.status_code == 409 and claim.json()["detail"] == CLAIM_PERSONAL_ONLY_MESSAGE
        refused_claim = await sales.post(
            prefix + "/claim",
            headers={"X-Test-Tenant": "operations", "Origin": "https://salesxray.example.test"},
        )
        assert refused_claim.status_code == 403
        assert refused_claim.json()["detail"] == WORKSPACE_UNAVAILABLE_MESSAGE
