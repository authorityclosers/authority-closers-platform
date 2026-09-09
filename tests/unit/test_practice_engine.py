"""Actual relational/audit pilot tests; SQLite is not PostgreSQL lock proof."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.db.models import model_metadata
from ac_platform.http.practice import install_practice_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.practice import arcade
from ac_platform.practice.application import (
    PracticeApplication,
    PracticeConflict,
    PracticeDenied,
    PracticeError,
    PracticeNotFound,
    buckets,
    validated_timezone,
)
from ac_platform.practice.models import (
    IMMUTABLE_MODELS,
    PracticeAttempt,
    PracticeCommand,
    PracticeLedgerEntry,
    PracticeParticipation,
    PracticeResponse,
    PracticeRewardClaim,
    PracticeSetVersion,
)
from ac_platform.tenancy.models import Membership, Tenant


class AwaitableSession:
    def __init__(self, database):
        self.database = database

    def get_transaction(self):
        return SimpleNamespace(sync_transaction=self.database.get_transaction())

    def get_bind(self):
        return self.database.get_bind()

    def add(self, row):
        self.database.add(row)

    async def scalar(self, statement):
        return self.database.scalar(statement)

    async def scalars(self, statement):
        return self.database.scalars(statement)

    async def execute(self, statement):
        return self.database.execute(statement)

    async def flush(self):
        self.database.flush()


@pytest.fixture
def state():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    model_metadata().create_all(engine)
    with Session(engine, expire_on_commit=False) as db, db.begin():
        state = SimpleNamespace(db=db, now=datetime(2026, 9, 7, 12, tzinfo=UTC))
        state.tenant, state.person, state.other = uuid4(), uuid4(), uuid4()
        db.add(Tenant(id=state.tenant, slug="practice-test", name="Practice test"))
        db.add_all(
            [
                Person(id=person, email_verified_at=state.now)
                for person in (state.person, state.other)
            ]
        )
        db.flush()
        db.add_all(
            [
                Membership(tenant_id=state.tenant, person_id=person, role="learner")
                for person in (state.person, state.other)
            ]
        )
        db.flush()
        state.session, state.other_session = uuid4(), uuid4()
        for person, session in ((state.person, state.session), (state.other, state.other_session)):
            db.add(
                IdentitySession(
                    id=session,
                    person_id=person,
                    selected_tenant_id=state.tenant,
                    token_hash=session.bytes * 2,
                    created_at=state.now,
                    expires_at=state.now + timedelta(days=1000),
                )
            )
        db.flush()
        state.actor = ActorContext(state.person, state.session, state.tenant)
        state.other_actor = ActorContext(state.other, state.other_session, state.tenant)
        state.async_db = AwaitableSession(db)
        state.app = PracticeApplication(
            state.async_db,
            academy_tenant_id=state.tenant,
            environment="test",
            preview_enabled=True,
            clock=lambda: state.now,
        )
        yield state
    engine.dispose()


async def save_zone(state, timezone="UTC"):
    return await state.app.save_profile(
        state.actor, key=uuid4().hex, timezone=timezone, expected_revision=0
    )


def selections(item):
    if item["kind"] == "match":
        return list(reversed(range(len(item["pairs"]))))
    if item["kind"] in {"order", "build"}:
        return list(reversed(item["answer"]))
    if item["kind"] == "branch":
        return [0]
    return [1]  # Valid authored choice; accuracy intentionally is NOT award eligibility.


async def finish(state, set_id="gaps", *, until_last_ack=False):
    result = await state.app.issue(state.actor, set_id=set_id, key=uuid4().hex)
    definition = arcade.set_snapshot(set_id)
    for item in definition["items"]:
        chosen = selections(item)
        while True:
            result = await state.app.respond(
                state.actor,
                UUID(result["id"]),
                key=uuid4().hex,
                item_id=item["id"],
                selections=chosen,
                expected_revision=result["revision"],
            )
            current = next(row for row in result["item_states"] if row["item_id"] == item["id"])
            if current["feedback"]["kind"] == "feedback":
                break
            chosen = [*chosen, 0]
        if until_last_ack and item == definition["items"][-1]:
            return result, current
        result = await state.app.acknowledge(
            state.actor,
            UUID(result["id"]),
            UUID(current["response_id"]),
            key=uuid4().hex,
            expected_revision=result["revision"],
        )
    return result


async def test_explicit_profile_required_and_no_claimable_browser_completion(state):
    assert (await state.app.profile(state.actor))["timezone"] is None
    with pytest.raises(PracticeConflict, match="timezone"):
        await state.app.issue(state.actor, set_id="gaps", key="first")
    assert state.db.scalar(select(func.count()).select_from(PracticeAttempt)) == 0
    await save_zone(state)
    result, last = await finish(state, until_last_ack=True)
    assert result["state"] == "in_progress" and result["reward_receipts"] == []
    assert state.db.scalar(select(func.count()).select_from(PracticeLedgerEntry)) == 0
    final = await state.app.acknowledge(
        state.actor,
        UUID(result["id"]),
        UUID(last["response_id"]),
        key="last-ack",
        expected_revision=result["revision"],
    )
    assert final["state"] == "completed"
    assert final["course_progress_affected"] is False
    assert final["reward_receipts"][0]["credits"] == 10
    assert final["reward_receipts"][0]["xp"] == 30
    assert any(row["feedback"]["reference_match"] is False for row in final["item_states"])
    replay = await state.app.acknowledge(
        state.actor,
        UUID(result["id"]),
        UUID(last["response_id"]),
        key="last-ack",
        expected_revision=result["revision"],
    )
    assert replay == final
    assert verify_audit_chain_sync(state.db, state.tenant).valid


@pytest.mark.parametrize("set_id", list(arcade._sets()))
async def test_every_editorial_kind_persists_and_completes(state, set_id):
    await save_zone(state)
    result = await finish(state, set_id)
    assert result["state"] == "completed"
    assert len(result["acknowledged_item_ids"]) == result["set"]["item_count"]
    assert all(
        row["acknowledged"] and row["feedback"]["responses_stored"] for row in result["item_states"]
    )
    assert (await state.app.attempt(state.actor, UUID(result["id"]))) == result


async def test_replay_payload_revision_order_and_append_only_reanswer_before_ack(state):
    await save_zone(state)
    issued = await state.app.issue(state.actor, set_id="gaps", key="issue")
    assert await state.app.issue(state.actor, set_id="gaps", key="issue") == issued
    with pytest.raises(PracticeConflict):
        await state.app.issue(state.actor, set_id="match", key="issue")
    attempt_id = UUID(issued["id"])
    with pytest.raises(PracticeConflict, match="current prompt"):
        await state.app.respond(
            state.actor,
            attempt_id,
            key="wrong-order",
            item_id="gaps-02",
            selections=[1],
            expected_revision=0,
        )
    with pytest.raises(PracticeConflict, match="changed"):
        await state.app.respond(
            state.actor,
            attempt_id,
            key="wrong-revision",
            item_id="gaps-01",
            selections=[1],
            expected_revision=1,
        )
    first = await state.app.respond(
        state.actor,
        attempt_id,
        key="response",
        item_id="gaps-01",
        selections=[1],
        expected_revision=0,
    )
    assert (
        await state.app.respond(
            state.actor,
            attempt_id,
            key="response",
            item_id="gaps-01",
            selections=[1],
            expected_revision=0,
        )
        == first
    )
    with pytest.raises(PracticeConflict):
        await state.app.respond(
            state.actor,
            attempt_id,
            key="response",
            item_id="gaps-01",
            selections=[0],
            expected_revision=0,
        )
    revised = await state.app.respond(
        state.actor,
        attempt_id,
        key="new-response",
        item_id="gaps-01",
        selections=[0],
        expected_revision=1,
    )
    assert revised["revision"] == 2
    with pytest.raises(PracticeConflict, match="not awaiting"):
        await state.app.acknowledge(
            state.actor,
            attempt_id,
            UUID(first["item_states"][0]["response_id"]),
            key="old-ack",
            expected_revision=2,
        )
    assert state.db.scalar(select(func.count()).select_from(PracticeResponse)) == 2


async def test_snapshot_survives_editorial_change_and_family_not_version_is_reward_key(
    state, monkeypatch
):
    await save_zone(state)
    issued = await state.app.issue(state.actor, set_id="gaps", key="pinned")
    original = arcade._sets()
    changed = {**original, "gaps": {**original["gaps"], "version": 2, "title": "Changed title"}}
    monkeypatch.setattr(arcade, "_sets", lambda: changed)
    resumed = await state.app.attempt(state.actor, UUID(issued["id"]))
    assert resumed["set"]["title"] == issued["set"]["title"] and resumed["set_version"] == 1
    first = await finish(state)
    monkeypatch.setattr(arcade, "_sets", lambda: original)
    second = await finish(state)
    assert first["set_version"] == 2 and second["set_version"] == 1
    assert first["reward_receipts"] and not second["reward_receipts"]


async def test_branch_restart_before_ack_preserves_history_and_rejects_old_feedback(state):
    await save_zone(state)
    result = await state.app.issue(state.actor, set_id="dialogue", key="branch-issue")
    item = result["set"]["items"][0]
    attempt_id = UUID(result["id"])
    path = [0]
    while True:
        result = await state.app.respond(
            state.actor,
            attempt_id,
            key=uuid4().hex,
            item_id=item["id"],
            selections=path,
            expected_revision=result["revision"],
        )
        latest = result["item_states"][0]
        if latest["feedback"]["kind"] == "feedback":
            break
        path = [*path, 0]
    prior_id = UUID(latest["response_id"])
    result = await state.app.respond(
        state.actor,
        attempt_id,
        key="restart-branch",
        item_id=item["id"],
        selections=[1],
        expected_revision=result["revision"],
    )
    assert result["item_states"][0]["selections"] == [1]
    with pytest.raises(PracticeConflict, match="not awaiting"):
        await state.app.acknowledge(
            state.actor,
            attempt_id,
            prior_id,
            key="outdated-branch-feedback",
            expected_revision=result["revision"],
        )
    if result["item_states"][0]["feedback"]["kind"] == "continue":
        with pytest.raises(PracticeConflict, match="saved conversation"):
            await state.app.respond(
                state.actor,
                attempt_id,
                key="wrong-prefix",
                item_id=item["id"],
                selections=[0, 0],
                expected_revision=result["revision"],
            )
    assert state.db.scalar(select(func.count()).select_from(PracticeResponse)) >= 2


async def test_revised_answer_acknowledges_only_latest_and_awards_once(state):
    await save_zone(state)
    result, current = await finish(state, until_last_ack=True)
    attempt_id = UUID(result["id"])
    revised = await state.app.respond(
        state.actor,
        attempt_id,
        key="revise-last",
        item_id=current["item_id"],
        selections=[0],
        expected_revision=result["revision"],
    )
    latest = next(row for row in revised["item_states"] if row["item_id"] == current["item_id"])
    assert latest["response_id"] != current["response_id"]
    complete = await state.app.acknowledge(
        state.actor,
        attempt_id,
        UUID(latest["response_id"]),
        key="ack-revised",
        expected_revision=revised["revision"],
    )
    assert complete["state"] == "completed" and len(complete["reward_receipts"]) == 1
    with pytest.raises(PracticeConflict, match="already complete"):
        await state.app.respond(
            state.actor,
            attempt_id,
            key="rewrite-completed",
            item_id=current["item_id"],
            selections=[1],
            expected_revision=complete["revision"],
        )


async def test_two_distinct_families_daily_cap_weekly_once_and_balanced_earned_ledger(state):
    await save_zone(state)
    for day in range(7):
        state.now = datetime(2026, 9, 7 + day, 12, tzinfo=UTC)
        first = await finish(state, "gaps")
        duplicate = await finish(state, "gaps")
        await finish(state, "match")
        capped = await finish(state, "sequence")
        assert any(row["kind"] == "daily_set" for row in first["reward_receipts"])
        assert duplicate["reward_receipts"] == [] and capped["reward_receipts"] == []
    progress = await state.app.progress(state.actor)
    assert progress["credits_balance"] == 180 and progress["xp_total"] == 420
    assert progress["actual_practice_days_this_week"] == 7
    assert sum(row["kind"] == "weekly_rhythm" for row in progress["recent_awards"]) == 1
    assert dict(
        state.db.execute(
            select(PracticeLedgerEntry.unit, func.sum(PracticeLedgerEntry.amount)).group_by(
                PracticeLedgerEntry.unit
            )
        ).all()
    ) == {"credits": 0, "xp": 0}
    assert state.db.scalar(select(func.count()).select_from(PracticeParticipation)) == 28
    state.now += timedelta(days=1)
    assert (await state.app.progress(state.actor))["actual_practice_days_this_week"] == 0


async def test_timezone_schedule_at_next_iso_week_no_rebucketing_and_pending_conflict(state):
    await save_zone(state, "Asia/Kolkata")
    first = await finish(state)
    scheduled = await state.app.save_profile(
        state.actor, key="change", timezone="America/New_York", expected_revision=1
    )
    assert scheduled["timezone"] == "Asia/Kolkata"
    assert scheduled["pending_effective_at"] == "2026-09-13T18:30:00+00:00"
    with pytest.raises(PracticeConflict, match="already scheduled"):
        await state.app.save_profile(
            state.actor, key="another-change", timezone="UTC", expected_revision=2
        )
    state.now = datetime(2026, 9, 13, 18, 29, 59, tzinfo=UTC)
    assert (await state.app.profile(state.actor))["timezone"] == "Asia/Kolkata"
    state.now += timedelta(seconds=1)
    effective = await state.app.profile(state.actor)
    assert effective["timezone"] == "America/New_York" and effective["pending_timezone"] is None
    assert (await state.app.attempt(state.actor, UUID(first["id"])))["reward_receipts"] == first[
        "reward_receipts"
    ]
    assert verify_audit_chain_sync(state.db, state.tenant).valid


@pytest.mark.parametrize(
    "value", ["", "Europe/NotHere", "../../UTC", "UTC\n", "utc", " UTC", "GMT+05:30"]
)
def test_reject_non_iana_timezone(value):
    with pytest.raises(PracticeError):
        validated_timezone(value)


@pytest.mark.parametrize(
    "stamp,zone,day,week",
    [
        ("2026-09-07T00:00:00+00:00", "America/New_York", "2026-09-06", "2026-08-31"),
        ("2026-09-06T18:30:00+00:00", "Asia/Kolkata", "2026-09-07", "2026-09-07"),
        ("2026-11-01T05:30:00+00:00", "America/New_York", "2026-11-01", "2026-10-26"),
        ("2026-11-01T06:30:00+00:00", "America/New_York", "2026-11-01", "2026-10-26"),
        ("2027-01-01T00:00:00+00:00", "UTC", "2027-01-01", "2026-12-28"),
    ],
)
def test_host_calendar_boundary(stamp, zone, day, week):
    actual = buckets(datetime.fromisoformat(stamp), zone)
    assert tuple(map(str, actual)) == (day, week)


async def test_tenant_person_session_isolation_and_replay_rechecks_identity(state):
    await save_zone(state)
    result = await finish(state)
    with pytest.raises(PracticeNotFound):
        await state.app.attempt(state.other_actor, UUID(result["id"]))
    assert (await state.app.progress(state.other_actor))["credits_balance"] == 0
    with pytest.raises(PracticeDenied):
        await state.app.attempt(
            ActorContext(state.person, state.session, uuid4(), frozenset({"owner"})),
            UUID(result["id"]),
        )
    state.db.get(IdentitySession, state.session).revoked_at = state.now
    state.db.flush()
    with pytest.raises(PracticeDenied):
        await state.app.attempt(state.actor, UUID(result["id"]))


async def test_final_ack_audit_and_award_all_rollback_when_journal_write_fails(state, monkeypatch):
    await save_zone(state)
    result, current = await finish(state, until_last_ack=True)
    before = state.db.scalar(select(func.count()).select_from(AuditEvent))
    original = state.app._award

    async def failing(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("Injected storage failure")

    monkeypatch.setattr(state.app, "_award", failing)
    with pytest.raises(RuntimeError, match="Injected"), state.db.begin_nested():
        await state.app.acknowledge(
            state.actor,
            UUID(result["id"]),
            UUID(current["response_id"]),
            key="rollback",
            expected_revision=result["revision"],
        )
    assert state.db.scalar(select(func.count()).select_from(AuditEvent)) == before
    assert state.db.scalar(select(func.count()).select_from(PracticeParticipation)) == 0
    assert state.db.scalar(select(func.count()).select_from(PracticeRewardClaim)) == 0
    assert state.db.scalar(select(func.count()).select_from(PracticeLedgerEntry)) == 0
    assert (
        state.db.scalar(select(PracticeCommand.id).where(PracticeCommand.key == "rollback")) is None
    )
    assert (await state.app.attempt(state.actor, UUID(result["id"]))) == result
    assert verify_audit_chain_sync(state.db, state.tenant).valid


async def test_immutable_history_orm_guards(state):
    await save_zone(state)
    await finish(state)
    for model in IMMUTABLE_MODELS:
        row = state.db.scalar(select(model))
        assert row is not None
        with pytest.raises(RuntimeError, match="immutable"), state.db.begin_nested():
            state.db.delete(row)
            state.db.flush()


async def test_http_complete_contract_strict_origin_idempotency_and_no_scope_inputs(state):
    settings = Settings(
        _env_file=None,
        environment="test",
        practice_arcade_preview_enabled=True,
        public_learner_tenant_id=state.tenant,
        operations_tenant_id=uuid4(),
    )
    app = FastAPI()
    register_problem_handlers(app)

    async def actor_dependency():
        if getattr(state, "signed_out", False):
            raise HTTPException(401, "Sign in")
        yield SimpleNamespace(
            database=state.async_db,
            resolved=SimpleNamespace(actor=state.actor, membership_role="learner"),
        )

    install_practice_http(app, settings=settings, require_actor=actor_dependency)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:3000"
    ) as client:
        body = {"timezone": "UTC", "expected_revision": 0}
        assert (await client.get("/v1/practice/profile")).json()["revision"] == 0
        assert (await client.put("/v1/practice/profile", json=body)).status_code == 422
        assert (
            await client.put("/v1/practice/profile", json=body, headers={"Idempotency-Key": "zone"})
        ).status_code == 403
        headers = {"Origin": "http://localhost:3000", "Idempotency-Key": "zone"}
        assert (
            await client.put(
                "/v1/practice/profile",
                json={**body, "tenant_id": str(state.tenant)},
                headers=headers,
            )
        ).status_code == 422
        assert (
            await client.put("/v1/practice/profile", json=body, headers=headers)
        ).status_code == 200
        headers["Idempotency-Key"] = "issue-http"
        issued = await client.post("/v1/practice/sets/gaps/attempts", json={}, headers=headers)
        assert issued.status_code == 200, issued.text
        assert issued.headers["cache-control"] == "private, no-store"
        attempt = issued.json()
        assert attempt["responses_stored"] and attempt["set_version"] == 1
        assert (
            await client.get(f"/v1/practice/attempts/{attempt['id']}?person_id=other")
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
            assert response.status_code == 200, response.text
            attempt = response.json()
            row = next(row for row in attempt["item_states"] if row["item_id"] == item["id"])
            headers["Idempotency-Key"] = uuid4().hex
            response = await client.post(
                f"/v1/practice/attempts/{attempt['id']}/feedback/{row['response_id']}/acknowledge",
                json={"expected_revision": attempt["revision"]},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            attempt = response.json()
        assert attempt["state"] == "completed"
        assert (await client.get("/v1/practice/progress")).json()["credits_balance"] == 10
        state.signed_out = True
        assert (await client.get(f"/v1/practice/attempts/{attempt['id']}")).status_code == 401


async def test_http_does_not_emit_success_before_dependency_transaction_commits(state):
    await save_zone(state)
    settings = Settings(
        _env_file=None,
        environment="test",
        practice_arcade_preview_enabled=True,
        public_learner_tenant_id=state.tenant,
        operations_tenant_id=uuid4(),
    )
    app = FastAPI()

    async def fail_at_commit():
        with state.db.begin_nested():
            yield SimpleNamespace(
                database=state.async_db,
                resolved=SimpleNamespace(actor=state.actor, membership_role="learner"),
            )
            raise RuntimeError("Injected deferred constraint failure at transaction exit")

    install_practice_http(app, settings=settings, require_actor=fail_at_commit)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://localhost:3000",
    ) as client:
        response = await client.post(
            "/v1/practice/sets/gaps/attempts",
            json={},
            headers={"Origin": "http://localhost:3000", "Idempotency-Key": "failed-commit"},
        )
        assert response.status_code == 500
        assert "reward_receipts" not in response.text and "in_progress" not in response.text
    assert state.db.scalar(select(func.count()).select_from(PracticeAttempt)) == 0
    assert (
        state.db.scalar(select(PracticeCommand.id).where(PracticeCommand.key == "failed-commit"))
        is None
    )


async def test_progress_batches_twenty_attempts_with_constant_select_count_and_exact_projection(
    state,
):
    await save_zone(state)
    first = await finish(state)
    issued = [first]
    statements = []

    def count_select(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append(statement)

    async def measured_progress():
        statements.clear()
        state.db.expire_all()
        bind = state.db.get_bind()
        event.listen(bind, "before_cursor_execute", count_select)
        try:
            result = await state.app.progress(state.actor)
            return result, len(statements)
        finally:
            event.remove(bind, "before_cursor_execute", count_select)

    one, one_count = await measured_progress()
    assert len(one["recent_attempts"]) == 1
    for index in range(19):
        state.now += timedelta(minutes=1)
        family = list(arcade._sets())[index % 8] if index < 18 else "gaps"
        issued.append(await state.app.issue(state.actor, set_id=family, key=uuid4().hex))
    last = issued[-1]
    answered = await state.app.respond(
        state.actor,
        UUID(last["id"]),
        key="partial-answer",
        item_id="gaps-01",
        selections=[1],
        expected_revision=0,
    )
    revised = await state.app.respond(
        state.actor,
        UUID(last["id"]),
        key="partial-revision",
        item_id="gaps-01",
        selections=[0],
        expected_revision=answered["revision"],
    )
    await state.app.acknowledge(
        state.actor,
        UUID(last["id"]),
        UUID(revised["item_states"][0]["response_id"]),
        key="partial-ack",
        expected_revision=revised["revision"],
    )
    # Expected summaries are derived from the full single-attempt contract,
    # outside the measured query window, including latest-only acknowledgment.
    full = [await state.app.attempt(state.actor, UUID(item["id"])) for item in reversed(issued)]
    expected = [
        {
            "id": item["id"],
            "set_id": item["set_id"],
            "set_version": item["set_version"],
            "title": item["set"]["title"],
            "state": item["state"],
            "revision": item["revision"],
            "acknowledged_count": len(item["acknowledged_item_ids"]),
            "item_count": item["set"]["item_count"],
            "issued_at": item["issued_at"],
            "completed_at": item["completed_at"],
        }
        for item in full
    ]
    twenty, twenty_count = await measured_progress()
    assert twenty["recent_attempts"] == expected
    assert one_count == twenty_count == 11
    assert one_count <= 12
    assert twenty["credits_balance"] == one["credits_balance"] == 10
    assert twenty["xp_total"] == one["xp_total"] == 30
    assert twenty["recent_awards"] == one["recent_awards"]
    assert twenty["actual_practice_days_this_week"] == one["actual_practice_days_this_week"] == 1
    # Progress summaries no longer retrieve stored private answer/feedback JSON.
    assert not any("practice_responses.selections" in statement for statement in statements)
    assert not any("practice_responses.feedback" in statement for statement in statements)


async def test_progress_batched_version_integrity_remains_fail_closed(state):
    await save_zone(state)
    issued = await state.app.issue(state.actor, set_id="gaps", key="pinned-progress")
    version = state.db.scalar(
        select(PracticeSetVersion).where(
            PracticeSetVersion.content_digest == issued["content_digest"]
        )
    )
    # Simulate a corrupted in-memory payload without rewriting persisted history.
    # The service must validate even an identity-map hit, not just trust the cache.
    original = version.snapshot["title"]
    try:
        version.snapshot["title"] = "Corrupted cached snapshot"
        with pytest.raises(PracticeConflict, match="could not be verified"):
            await state.app.progress(state.actor)
    finally:
        version.snapshot["title"] = original
    assert (await state.app.progress(state.actor))["recent_attempts"][0]["title"] == original


async def test_progress_counts_only_latest_feedback_even_if_stale_ack_history_exists(state):
    await save_zone(state)
    issued, last = await finish(state, until_last_ack=True)
    # Deliberately construct an unsupported extra response in this disposable
    # fixture after an earlier item's acknowledgment, to prove the batched read
    # preserves _items' latest-only semantics even with inconsistent history.
    initial_item = issued["item_states"][0]
    state.db.add(
        PracticeResponse(
            id=uuid4(),
            tenant_id=state.tenant,
            person_id=state.person,
            attempt_id=UUID(issued["id"]),
            item_id=initial_item["item_id"],
            sequence=issued["revision"] + 1,
            selections=[0],
            feedback={
                "kind": "feedback",
                "reference_match": True,
                "explanation": "Fixture only",
                "responses_stored": True,
                "course_progress_affected": False,
            },
            created_at=state.now,
        )
    )
    state.db.flush()
    single = await state.app.attempt(state.actor, UUID(issued["id"]))
    progress = await state.app.progress(state.actor)
    assert initial_item["item_id"] not in single["acknowledged_item_ids"]
    assert progress["recent_attempts"][0]["acknowledged_count"] == len(
        single["acknowledged_item_ids"]
    )
    assert last["item_id"] not in single["acknowledged_item_ids"]
