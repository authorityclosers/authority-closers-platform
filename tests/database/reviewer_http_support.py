"""Synthetic identities with actual reviewer HTTP, sessions, PostgreSQL and mail jobs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import FastAPI

from ac_platform.application.settings import Settings
from ac_platform.http.admin_learning import install_admin_learning_http
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation_reviews import install_conversation_review_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.reviewer_auth import install_reviewer_identity_http
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.providers import EmailMessage, FakeEmailAdapter
from ac_platform.worker import DurableWorker, build_default_dispatcher
from tests.database.test_conversation_reviews_postgresql import ReviewCase


def settings_for(case: ReviewCase, *, origin: str = "https://admin.test") -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        public_app_url="https://learner.test",
        admin_app_url=origin,
        coach_app_url="https://coach.test",
        api_url="https://api.test",
        public_learner_tenant_id=case.source_actor.tenant_id,
        operations_tenant_id=case.operations_tenant_id,
        external_side_effects_hold=False,
    )


def app_for(case: ReviewCase, settings: Settings) -> FastAPI:
    app = FastAPI()
    register_problem_handlers(app)
    account = install_identity_http(app, settings=settings, sessions=case.sessions)
    install_admin_learning_http(app, settings=settings, require_actor=account)
    reviewer = install_reviewer_identity_http(
        app, settings=settings, sessions=case.sessions, clock=lambda: case.prepared.state.now
    )
    install_conversation_review_http(
        app,
        settings=settings,
        require_actor=account,
        require_reviewer=reviewer,
        storage=case.prepared.storage,
        clock=lambda: case.prepared.state.now,
    )
    return app


async def account_token(case: ReviewCase, settings: Settings, person_id: UUID) -> str:
    async with case.sessions() as database, database.begin():
        identity = AsyncIdentityApplication(
            database, token_pepper=settings.session_token_pepper.get_secret_value()
        )
        issued = await identity.issue_authenticated_session(person_id)
        return issued.token


def mail_worker(case: ReviewCase, settings: Settings) -> tuple[DurableWorker, FakeEmailAdapter]:
    provider = FakeEmailAdapter()
    worker = DurableWorker(
        case.sessions,
        settings=settings,
        dispatcher=build_default_dispatcher(settings, provider=provider),
    )
    return worker, provider


async def deliver(
    worker: DurableWorker, provider: FakeEmailAdapter, template: str, email: str
) -> EmailMessage:
    assert await worker.prepare()
    await worker.run_once()
    matches = [
        message
        for message in provider.sent_messages
        if message.template == template and message.to.casefold() == email.casefold()
    ]
    assert matches, "The transactional test mail provider did not receive the expected message."
    return matches[-1]


def invitation_body(case: ReviewCase, email: str) -> dict[str, Any]:
    return {
        "run_id": str(case.report_run_id),
        "invited_email": email,
        "allowed_lenses": ["sales", "technical", "ux"],
        "expires_at_epoch": int(case.prepared.state.now.timestamp()) + 1800,
    }
