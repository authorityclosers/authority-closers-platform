"""Explicit deployment pilot settings and real relational practice/HTTP contracts."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.http.practice import install_practice_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.practice.application import PracticeApplication, PracticeDenied
from ac_platform.practice.models import (
    PracticeAttempt,
    PracticeCommand,
    PracticeLedgerEntry,
    PracticeParticipation,
    PracticeRewardClaim,
)
from ac_platform.tenancy.models import Membership
from tests.unit import test_practice_engine as engine_tests
from tests.unit.application.test_settings import _deployment_values


@pytest.fixture
def state() -> Iterator[SimpleNamespace]:
    yield from engine_tests.state.__wrapped__()


def _settings(environment: str, tenant: UUID, **overrides: Any) -> Settings:
    # Existing deployment-valid fixtures contain synthetic credentials only;
    # Settings validation never constructs a provider or connects to this URL.
    values: dict[str, Any] = (
        _deployment_values(environment) if environment in {"staging", "production"} else {}
    )
    values.update(
        environment=environment,
        public_learner_tenant_id=tenant,
        operations_tenant_id=uuid4(),
        practice_arcade_preview_enabled=False,
        practice_pilot_enabled=True,
        practice_pilot_tenant_id=tenant,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _pilot(state: SimpleNamespace, environment: str) -> PracticeApplication:
    return PracticeApplication(
        state.async_db,
        academy_tenant_id=state.tenant,
        environment=environment,
        preview_enabled=False,
        pilot_enabled=True,
        clock=lambda: state.now,
    )


def _http(
    state: SimpleNamespace,
    environment: str,
    *,
    pilot_enabled: bool = True,
    fail_commit: bool = False,
) -> tuple[FastAPI, Settings]:
    settings = _settings(environment, state.tenant, practice_pilot_enabled=pilot_enabled)
    app = FastAPI()
    register_problem_handlers(app)

    async def actor_dependency() -> Any:
        if getattr(state, "signed_out", False):
            raise HTTPException(401, "Sign in")
        # The domain still queries the real persisted person/session/membership.
        # This fixture replaces only the enclosing HTTP authentication dependency.
        with state.db.begin_nested():
            yield SimpleNamespace(
                database=state.async_db,
                resolved=SimpleNamespace(
                    actor=getattr(state, "request_actor", state.actor),
                    membership_role="learner",
                ),
            )
            if fail_commit:
                raise RuntimeError("Injected pilot deferred constraint failure")

    install_practice_http(app, settings=settings, require_actor=actor_dependency)
    return app, settings


@pytest.mark.parametrize("environment", ["test", "staging", "production"])
def test_pilot_is_explicit_default_disabled_and_exact_tenant_configured(environment: str) -> None:
    tenant = uuid4()
    disabled = _settings(environment, tenant, practice_pilot_enabled=False)
    assert not disabled.practice_arcade_preview_enabled
    assert disabled.practice_tenant_id is None
    enabled = _settings(environment, tenant)
    assert enabled.practice_pilot_enabled
    assert enabled.practice_tenant_id == tenant
    assert enabled.practice_pilot_tenant_id == enabled.public_learner_tenant_id
    assert enabled.operations_tenant_id != tenant
    defaults = Settings(_env_file=None, environment="test")
    assert not defaults.practice_pilot_enabled and defaults.practice_pilot_tenant_id is None
    assert defaults.practice_tenant_id is None


@pytest.mark.parametrize("environment", ["test", "staging", "production"])
@pytest.mark.parametrize(
    "invalid_scope",
    ["missing_pilot", "missing_public", "other_pilot", "operations_match", "missing_operations"],
)
def test_enabled_pilot_requires_exact_public_and_distinct_operations_tenants(
    environment: str, invalid_scope: str
) -> None:
    tenant = uuid4()
    changes = {
        "missing_pilot": {"practice_pilot_tenant_id": None},
        "missing_public": {"public_learner_tenant_id": None},
        "other_pilot": {"practice_pilot_tenant_id": uuid4()},
        "operations_match": {"operations_tenant_id": tenant},
        "missing_operations": {"operations_tenant_id": None},
    }
    with pytest.raises(ValidationError):
        _settings(environment, tenant, **changes[invalid_scope])


@pytest.mark.parametrize("environment", ["local", "development"])
def test_pilot_rejects_unapproved_environments(environment: str) -> None:
    with pytest.raises(ValidationError):
        _settings(environment, uuid4())


@pytest.mark.parametrize("environment", ["test", "staging", "production"])
def test_pilot_and_preview_cannot_be_enabled_together(environment: str) -> None:
    with pytest.raises(ValidationError):
        _settings(environment, uuid4(), practice_arcade_preview_enabled=True)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_local_preview_still_cannot_enable_a_deployed_pilot(environment: str) -> None:
    with pytest.raises(ValidationError):
        _settings(
            environment,
            uuid4(),
            practice_pilot_enabled=False,
            practice_arcade_preview_enabled=True,
        )


@pytest.mark.parametrize("environment", ["local", "test"])
def test_existing_local_preview_remains_available(environment: str) -> None:
    tenant = uuid4()
    settings = _settings(
        environment,
        tenant,
        practice_pilot_enabled=False,
        practice_pilot_tenant_id=None,
        practice_arcade_preview_enabled=True,
    )
    assert settings.practice_tenant_id == tenant


@pytest.mark.parametrize("invalid", ["wrong_tenant", "both_modes", "local_environment"])
def test_http_composition_revalidates_settings_copy_before_mounting_routes(invalid: str) -> None:
    settings = _settings("production", uuid4())
    changes = {
        "wrong_tenant": {"practice_pilot_tenant_id": uuid4()},
        "both_modes": {"practice_arcade_preview_enabled": True},
        "local_environment": {"environment": "local"},
    }
    app = FastAPI()

    async def unused_actor() -> None:
        raise AssertionError("invalid configuration must stop before authentication")

    with pytest.raises(ValueError):
        install_practice_http(
            app,
            settings=settings.model_copy(update=changes[invalid]),
            require_actor=unused_actor,
        )
    assert not any(getattr(route, "path", "").startswith("/v1/practice") for route in app.routes)


@pytest.mark.parametrize("environment", ["staging", "production"])
async def test_pilot_uses_existing_durable_completion_rewards_and_exact_replay(
    state: SimpleNamespace, environment: str
) -> None:
    state.app = _pilot(state, environment)
    await engine_tests.save_zone(state)
    attempt, last = await engine_tests.finish(state, until_last_ack=True)
    assert attempt["state"] == "in_progress" and attempt["reward_receipts"] == []
    assert state.db.scalar(select(func.count()).select_from(PracticeRewardClaim)) == 0
    intent = {
        "key": "pilot-final-ack",
        "expected_revision": attempt["revision"],
    }
    result = await state.app.acknowledge(
        state.actor, UUID(attempt["id"]), UUID(last["response_id"]), **intent
    )
    assert result["state"] == "completed" and result["course_progress_affected"] is False
    assert [(row["credits"], row["xp"]) for row in result["reward_receipts"]] == [(10, 30)]
    # Re-read database state through a newly composed application, rather than
    # accepting the response as persistence or idempotency evidence.
    state.db.expire_all()
    fresh = _pilot(state, environment)
    assert await fresh.attempt(state.actor, UUID(attempt["id"])) == result
    assert (
        await fresh.acknowledge(
            state.actor, UUID(attempt["id"]), UUID(last["response_id"]), **intent
        )
        == result
    )
    assert state.db.scalar(select(func.count()).select_from(PracticeAttempt)) == 1
    assert state.db.scalar(select(func.count()).select_from(PracticeParticipation)) == 1
    assert state.db.scalar(select(func.count()).select_from(PracticeRewardClaim)) == 1
    assert state.db.scalar(select(func.count()).select_from(PracticeLedgerEntry)) == 4
    balances = state.db.execute(
        select(PracticeLedgerEntry.unit, func.sum(PracticeLedgerEntry.amount)).group_by(
            PracticeLedgerEntry.unit
        )
    ).all()
    assert dict(balances) == {"credits": 0, "xp": 0}
    assert verify_audit_chain_sync(state.db, state.tenant).valid


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize(
    "denial", ["foreign_tenant", "revoked_session", "inactive_member", "unverified_person"]
)
async def test_pilot_replay_rechecks_canonical_identity_and_tenant(
    state: SimpleNamespace, environment: str, denial: str
) -> None:
    state.app = _pilot(state, environment)
    await engine_tests.save_zone(state)
    attempt = await state.app.issue(state.actor, set_id="gaps", key="pilot-issue")
    actor = state.actor
    if denial == "foreign_tenant":
        actor = replace(actor, tenant_id=uuid4())
    elif denial == "revoked_session":
        state.db.get(IdentitySession, state.session).revoked_at = state.now
    elif denial == "inactive_member":
        member = state.db.scalar(select(Membership).where(Membership.person_id == state.person))
        member.status = "inactive"
        member.ended_at = state.now
    else:
        state.db.get(Person, state.person).email_verified_at = None
    state.db.flush()
    with pytest.raises(PracticeDenied):
        await state.app.issue(actor, set_id="gaps", key="pilot-issue")
    with pytest.raises(PracticeDenied):
        await state.app.attempt(actor, UUID(attempt["id"]))
    assert state.db.scalar(select(func.count()).select_from(PracticeAttempt)) == 1
    assert state.db.scalar(select(func.count()).select_from(PracticeRewardClaim)) == 0


@pytest.mark.parametrize(
    ("environment", "preview", "pilot"),
    [
        ("staging", False, False),
        ("production", False, False),
        ("production", True, False),
        ("test", True, True),
        ("local", False, True),
        ("development", False, True),
    ],
)
def test_domain_constructor_cannot_bypass_disabled_or_incompatible_modes(
    state: SimpleNamespace, environment: str, preview: bool, pilot: bool
) -> None:
    with pytest.raises(PracticeDenied):
        PracticeApplication(
            state.async_db,
            academy_tenant_id=state.tenant,
            environment=environment,
            preview_enabled=preview,
            pilot_enabled=pilot,
        )
    assert state.db.scalar(select(func.count()).select_from(PracticeAttempt)) == 0


@pytest.mark.parametrize("environment", ["staging", "production"])
async def test_deployed_http_pilot_keeps_durable_contract_and_excludes_stateless_check(
    state: SimpleNamespace, environment: str
) -> None:
    app, settings = _http(state, environment)
    origin = str(settings.public_app_url).rstrip("/")
    headers = {"Origin": origin, "Idempotency-Key": "pilot-timezone"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        assert (await client.get("/v1/practice/sets")).status_code == 200
        assert (await client.get("/v1/practice/sets/gaps")).status_code == 200
        assert (await client.get("/v1/practice/focus")).status_code == 200
        assert (
            await client.post(
                "/v1/practice/sets/gaps/check",
                json={"item_id": "gaps-01", "selections": [0]},
                headers=headers,
            )
        ).status_code == 404
        zone = {"timezone": "UTC", "expected_revision": 0}
        for wrong_origin in (None, "https://wrong.test", str(settings.admin_app_url).rstrip("/")):
            unsafe_headers = {"Idempotency-Key": "pilot-timezone"}
            if wrong_origin is not None:
                unsafe_headers["Origin"] = wrong_origin
            assert (
                await client.put("/v1/practice/profile", json=zone, headers=unsafe_headers)
            ).status_code == 403
        assert (
            await client.put("/v1/practice/profile", json=zone, headers=headers)
        ).status_code == 200
        headers["Idempotency-Key"] = "pilot-http-issue"
        for selector in ("tenant_id", "person_id", "reward", "completed"):
            assert (
                await client.post(
                    "/v1/practice/sets/gaps/attempts", json={selector: "forged"}, headers=headers
                )
            ).status_code == 422
        issued = await client.post("/v1/practice/sets/gaps/attempts", json={}, headers=headers)
        assert issued.status_code == 200
        assert issued.headers["cache-control"] == "private, no-store"
        attempt = issued.json()
        assert attempt["responses_stored"]
        assert (
            await client.get(f"/v1/practice/attempts/{attempt['id']}?tenant_id={uuid4()}")
        ).status_code == 422
        for item in attempt["set"]["items"]:
            headers["Idempotency-Key"] = uuid4().hex
            response = await client.post(
                f"/v1/practice/attempts/{attempt['id']}/responses",
                json={
                    "item_id": item["id"],
                    "selections": [1],
                    "expected_revision": attempt["revision"],
                },
                headers=headers,
            )
            assert response.status_code == 200
            attempt = response.json()
            row = next(row for row in attempt["item_states"] if row["item_id"] == item["id"])
            headers["Idempotency-Key"] = uuid4().hex
            response = await client.post(
                f"/v1/practice/attempts/{attempt['id']}/feedback/{row['response_id']}/acknowledge",
                json={"expected_revision": attempt["revision"]},
                headers=headers,
            )
            assert response.status_code == 200
            attempt = response.json()
        assert attempt["state"] == "completed" and not attempt["course_progress_affected"]
        progress = (await client.get("/v1/practice/progress")).json()
        assert progress["credits_balance"] == 10 and progress["xp_total"] == 30
        state.request_actor = replace(state.actor, tenant_id=uuid4())
        assert (await client.get("/v1/practice/progress")).status_code == 403
        state.request_actor = state.actor
        state.db.get(IdentitySession, state.session).revoked_at = state.now
        state.db.flush()
        assert (await client.get(f"/v1/practice/attempts/{attempt['id']}")).status_code == 403
        state.signed_out = True
        assert (await client.get("/v1/practice/sets")).status_code == 401
    assert state.db.scalar(select(func.count()).select_from(PracticeRewardClaim)) == 1
    assert verify_audit_chain_sync(state.db, state.tenant).valid


@pytest.mark.parametrize("environment", ["staging", "production"])
async def test_disabled_deployed_pilot_mounts_no_practice_routes(
    state: SimpleNamespace, environment: str
) -> None:
    app, settings = _http(state, environment, pilot_enabled=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=str(settings.public_app_url)
    ) as client:
        for path in ("/sets", "/profile", "/progress", "/focus"):
            assert (await client.get(f"/v1/practice{path}")).status_code == 404
    assert state.db.scalar(select(func.count()).select_from(PracticeAttempt)) == 0


@pytest.mark.parametrize("environment", ["staging", "production"])
async def test_deployed_pilot_does_not_emit_success_before_transaction_commit(
    state: SimpleNamespace, environment: str
) -> None:
    state.app = _pilot(state, environment)
    await engine_tests.save_zone(state)
    initial_audits = state.db.scalar(select(func.count()).select_from(AuditEvent))
    app, settings = _http(state, environment, fail_commit=True)
    origin = str(settings.public_app_url).rstrip("/")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url=origin
    ) as client:
        response = await client.post(
            "/v1/practice/sets/gaps/attempts",
            json={},
            headers={"Origin": origin, "Idempotency-Key": "pilot-failed-commit"},
        )
        assert response.status_code == 500
        assert "reward_receipts" not in response.text and "in_progress" not in response.text
    assert state.db.scalar(select(func.count()).select_from(PracticeAttempt)) == 0
    assert state.db.scalar(select(func.count()).select_from(AuditEvent)) == initial_audits
    assert (
        state.db.scalar(
            select(PracticeCommand.id).where(PracticeCommand.key == "pilot-failed-commit")
        )
        is None
    )
    assert verify_audit_chain_sync(state.db, state.tenant).valid
