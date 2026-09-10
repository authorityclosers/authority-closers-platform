"""Relational Focus policy and HTTP boundary proof, with no deployment activation."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.http.practice import install_practice_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.practice.application import PracticeDenied, PracticeNotFound
from ac_platform.practice.focus import FocusApplication, FocusConflict
from ac_platform.practice.focus_models import PracticeFocusEvent, PracticeFocusRun
from ac_platform.practice.models import PracticeCommand, PracticeLedgerEntry
from tests.unit import test_practice_engine as engine_tests
from tests.unit.test_practice_engine import save_zone


@pytest.fixture
def state():
    yield from engine_tests.state.__wrapped__()


async def issue(state):
    return await state.app.issue(state.actor, set_id="gaps", key=uuid4().hex)


async def start(state, attempt=None, **overrides):
    focus = FocusApplication(state.app)
    attempt = await issue(state) if attempt is None else attempt
    arguments = {
        "key": uuid4().hex,
        "expected_revision": (await focus.summary(state.actor))["revision"],
        "expected_attempt_revision": attempt["revision"],
        **overrides,
    }
    return attempt, await focus.start(state.actor, UUID(attempt["id"]), **arguments)


async def advance(state, attempt, *, count=1, acknowledge=True):
    remaining = [
        item
        for item in attempt["set"]["items"]
        if item["id"] not in attempt["acknowledged_item_ids"]
    ]
    for item in remaining[:count]:
        attempt = await state.app.respond(
            state.actor,
            UUID(attempt["id"]),
            key=uuid4().hex,
            item_id=item["id"],
            selections=[1],
            expected_revision=attempt["revision"],
        )
        row = next(row for row in attempt["item_states"] if row["item_id"] == item["id"])
        if acknowledge:
            attempt = await state.app.acknowledge(
                state.actor,
                UUID(attempt["id"]),
                UUID(row["response_id"]),
                key=uuid4().hex,
                expected_revision=attempt["revision"],
            )
    return attempt


async def end(state, attempt, run, **overrides):
    focus = FocusApplication(state.app)
    return await focus.end(
        state.actor,
        UUID(run["id"]),
        **{
            "key": uuid4().hex,
            "expected_revision": (await focus.summary(state.actor))["revision"],
            "expected_attempt_revision": attempt["revision"],
            **overrides,
        },
    )


async def test_summary_requires_no_timezone_inference_or_persistence(state):
    summary = await FocusApplication(state.app).summary(state.actor)
    assert summary == {
        "policy_version": "arcade-focus-local-2026-09-08-v1",
        "charges": 3,
        "capacity": 3,
        "revision": 0,
        "local_day": None,
        "timezone": None,
        "active_run": None,
    }
    assert state.db.scalar(select(func.count()).select_from(PracticeFocusEvent)) == 0
    assert state.db.scalar(select(func.count()).select_from(AuditEvent)) == 0


@pytest.mark.parametrize("answered", [False, True])
async def test_explicit_end_is_free_before_first_ack_and_preserves_answers(state, answered):
    await save_zone(state)
    attempt, result = await start(state)
    if answered:
        attempt = await advance(state, attempt, acknowledge=False)
    ended = await end(state, attempt, result["run"])
    assert ended["summary"]["charges"] == 3
    assert ended["run"]["state"] == "ended" and ended["run"]["exit_cost"] == 0
    assert ended["summary"]["active_run"] is None
    assert await state.app.attempt(state.actor, UUID(attempt["id"])) == attempt
    assert state.db.scalar(select(func.count()).select_from(PracticeLedgerEntry)) == 0


async def test_confirmed_end_after_ack_costs_once_with_audited_replay_and_no_reward_loss(state):
    await save_zone(state)
    attempt, result = await start(state)
    attempt = await advance(state, attempt)
    arguments = {
        "key": "explicit-end",
        "expected_revision": 1,
        "expected_attempt_revision": attempt["revision"],
    }
    ended = await end(state, attempt, result["run"], **arguments)
    assert ended["summary"]["charges"] == 2 and ended["run"]["exit_cost"] == 1
    assert await end(state, attempt, result["run"], **arguments) == ended
    assert state.db.scalar(select(func.count()).select_from(PracticeFocusEvent)) == 2
    resumed = await advance(state, attempt, count=100)
    assert resumed["state"] == "completed"
    progress = await state.app.progress(state.actor)
    assert progress["credits_balance"] == 10 and progress["xp_total"] == 30
    assert (await FocusApplication(state.app).summary(state.actor))["charges"] == 2
    assert verify_audit_chain_sync(state.db, state.tenant).valid


async def test_reads_pause_and_wrong_response_have_no_focus_cost(state):
    await save_zone(state)
    attempt, result = await start(state)
    for _ in range(4):
        await state.app.attempt(state.actor, UUID(attempt["id"]))
        assert (await FocusApplication(state.app).summary(state.actor)) == result["summary"]
    await advance(state, attempt, acknowledge=False)
    assert (await FocusApplication(state.app).summary(state.actor))["charges"] == 3
    assert state.db.scalar(select(func.count()).select_from(PracticeFocusEvent)) == 1


async def test_zero_blocks_only_new_focus_standard_and_resumption_still_work(state):
    await save_zone(state)
    for expected in (2, 1, 0):
        attempt, result = await start(state)
        attempt = await advance(state, attempt)
        ended = await end(state, attempt, result["run"])
        assert ended["summary"]["charges"] == expected
    standard = await issue(state)
    with pytest.raises(FocusConflict) as error:
        await start(state, standard)
    assert error.value.reason == "focus_empty"
    assert (await advance(state, standard, count=100))["state"] == "completed"
    assert (await FocusApplication(state.app).summary(state.actor))["charges"] == 0
    assert (await state.app.progress(state.actor))["credits_balance"] == 10


@pytest.mark.parametrize("initial_cost", [False, True])
async def test_completion_refills_one_capped_at_three_and_ack_replay_is_free(state, initial_cost):
    await save_zone(state)
    if initial_cost:
        first, started = await start(state)
        await end(state, await advance(state, first), started["run"])
    attempt, started = await start(state)
    completed = await advance(state, attempt, count=100)
    run = await FocusApplication(state.app)._run(state.actor, UUID(started["run"]["id"]))
    assert run.state == "completed" and run.completion_restore == int(initial_cost)
    assert (await FocusApplication(state.app).summary(state.actor))["charges"] == 3
    command = state.db.scalar(
        select(PracticeCommand)
        .where(PracticeCommand.operation == "feedback_acknowledged")
        .order_by(PracticeCommand.created_at.desc(), PracticeCommand.id)
    )
    assert command is not None and completed["reward_receipts"]
    # Replaying original start reads the current completed run; it does not reactivate/refill.
    original = state.db.scalar(
        select(PracticeCommand).where(
            PracticeCommand.result_id == run.id, PracticeCommand.operation == "focus_started"
        )
    )
    replay = await FocusApplication(state.app).start(
        state.actor,
        UUID(attempt["id"]),
        key=original.key,
        expected_revision=started["summary"]["revision"] - 1,
        expected_attempt_revision=0,
    )
    assert replay["run"]["state"] == "completed" and replay["summary"]["charges"] == 3


async def test_single_active_and_single_lifetime_opt_in_before_first_answer(state):
    await save_zone(state)
    attempt, result = await start(state)
    with pytest.raises(FocusConflict) as error:
        await start(state)
    assert error.value.reason == "active_run_conflict"
    await end(state, attempt, result["run"])
    with pytest.raises(FocusConflict) as error:
        await start(state, attempt)
    assert error.value.reason == "not_eligible"
    answered = await advance(state, await issue(state), acknowledge=False)
    with pytest.raises(FocusConflict) as error:
        await start(state, answered)
    assert error.value.reason == "attempt_started"


async def test_stale_end_cannot_silently_charge_for_concurrent_ack(state):
    await save_zone(state)
    attempt, result = await start(state)
    await advance(state, attempt)
    with pytest.raises(FocusConflict) as error:
        await end(state, attempt, result["run"])
    assert error.value.reason == "revision_conflict"
    assert (await FocusApplication(state.app).summary(state.actor))["charges"] == 3


async def test_next_day_reset_is_lazy_audited_once_and_history_is_not_rebucketed(state):
    await save_zone(state, "Asia/Kolkata")
    attempt, result = await start(state)
    await end(state, await advance(state, attempt), result["run"])
    history = [
        (e.id, e.local_day, e.timezone) for e in state.db.scalars(select(PracticeFocusEvent))
    ]
    state.now += timedelta(days=1)
    before_count = state.db.scalar(select(func.count()).select_from(AuditEvent))
    summary = await FocusApplication(state.app).summary(state.actor)
    assert summary["charges"] == 3 and summary["revision"] == 2
    assert state.db.scalar(select(func.count()).select_from(AuditEvent)) == before_count
    _, next_run = await start(state)
    assert next_run["summary"]["revision"] == 4
    events = list(
        state.db.scalars(select(PracticeFocusEvent).order_by(PracticeFocusEvent.revision))
    )
    assert [e.kind for e in events] == ["started", "ended", "day_reset", "started"]
    assert [(e.id, e.local_day, e.timezone) for e in events[:2]] == history


async def test_scheduled_timezone_backward_date_does_not_reissue_focus(state):
    await save_zone(state, "Pacific/Kiritimati")
    scheduled = await state.app.save_profile(
        state.actor, key="zone-next", timezone="Pacific/Honolulu", expected_revision=1
    )
    state.now = datetime.fromisoformat(scheduled["pending_effective_at"]) - timedelta(seconds=1)
    attempt, result = await start(state)
    await end(state, await advance(state, attempt), result["run"])
    old = await FocusApplication(state.app).summary(state.actor)
    state.now += timedelta(seconds=1)
    summary = await FocusApplication(state.app).summary(state.actor)
    assert summary["timezone"] == "Pacific/Honolulu"
    assert summary["local_day"] == old["local_day"] and summary["charges"] == 2
    state.now += timedelta(days=1)
    assert (await FocusApplication(state.app).summary(state.actor))["charges"] == 3


async def test_person_tenant_and_revoked_session_cannot_see_or_mutate_focus(state):
    await save_zone(state)
    attempt, result = await start(state)
    focus = FocusApplication(state.app)
    assert (await focus.summary(state.other_actor))["active_run"] is None
    with pytest.raises(PracticeNotFound):
        await focus.end(
            state.other_actor,
            UUID(result["run"]["id"]),
            key="other",
            expected_revision=0,
            expected_attempt_revision=0,
        )
    with pytest.raises(PracticeDenied):
        await focus.summary(ActorContext(state.person, state.session, uuid4()))
    state.db.get(IdentitySession, state.session).revoked_at = state.now
    state.db.flush()
    with pytest.raises(PracticeDenied):
        await focus.summary(state.actor)


async def test_focus_write_and_audit_roll_back_together_and_event_orm_is_immutable(state):
    await save_zone(state)
    before = state.db.scalar(select(func.count()).select_from(AuditEvent))
    with pytest.raises(RuntimeError, match="abort"), state.db.begin_nested():
        await start(state)
        raise RuntimeError("abort")
    assert state.db.scalar(select(func.count()).select_from(PracticeFocusEvent)) == 0
    assert state.db.scalar(select(func.count()).select_from(PracticeFocusRun)) == 0
    assert state.db.scalar(select(func.count()).select_from(AuditEvent)) == before
    await start(state)
    with pytest.raises(RuntimeError, match="immutable"), state.db.begin_nested():
        entry = state.db.scalar(select(PracticeFocusEvent))
        entry.charges_after = 1
        state.db.flush()


async def test_http_focus_contract_origin_scope_payload_and_function_commit(state):
    await save_zone(state)
    attempt = await issue(state)
    app = FastAPI()
    register_problem_handlers(app)
    settings = Settings(
        _env_file=None,
        environment="test",
        practice_arcade_preview_enabled=True,
        public_learner_tenant_id=state.tenant,
        operations_tenant_id=uuid4(),
    )

    async def dependency():
        with state.db.begin_nested():
            yield SimpleNamespace(
                database=state.async_db,
                resolved=SimpleNamespace(actor=state.actor, membership_role="learner"),
            )
            if getattr(state, "commit_failure", False):
                raise RuntimeError("synthetic deferred commit failure")

    install_practice_http(app, settings=settings, require_actor=dependency)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://localhost:3000",
    ) as client:
        assert (await client.get("/v1/practice/focus?tenant_id=other")).status_code == 422
        summary = await client.get("/v1/practice/focus")
        assert summary.headers["cache-control"] == "private, no-store"
        path = f"/v1/practice/attempts/{attempt['id']}/focus"
        body = {"expected_revision": 0, "expected_attempt_revision": 0}
        headers = {"Idempotency-Key": "focus-http"}
        assert (await client.post(path, json=body, headers=headers)).status_code == 403
        headers["Origin"] = "http://localhost:3000"
        assert (
            await client.post(path, json={**body, "charges": 3}, headers=headers)
        ).status_code == 422
        assert (
            await client.post(path, json={**body, "expected_revision": True}, headers=headers)
        ).status_code == 422
        state.commit_failure = True
        failure = await client.post(path, json=body, headers=headers)
        assert failure.status_code == 500 and "active_run" not in failure.text
        assert state.db.scalar(select(func.count()).select_from(PracticeFocusRun)) == 0
        state.commit_failure = False
        response = await client.post(path, json=body, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["run"]["set_id"] == "gaps" and data["run"]["state"] == "active"
        headers["Idempotency-Key"] = "not-replay"
        conflict = await client.post(path, json=body, headers=headers)
        assert conflict.status_code == 409 and conflict.json()["detail"]["reason"] == "not_eligible"
        ended = await client.post(
            f"/v1/practice/focus/runs/{data['run']['id']}/end",
            json={**body, "expected_revision": 1},
            headers={**headers, "Idempotency-Key": "end-http"},
        )
        assert ended.status_code == 200 and ended.json()["run"]["exit_cost"] == 0
