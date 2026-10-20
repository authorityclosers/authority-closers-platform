"""Provider keys on PostgreSQL (Providers hub slice 2, owner 20 Oct 2026).

A control account adds a key right after signing in; it is sealed (never stored or answered
in clear), a new key retires the one before it, the free check reports in plain words and
lists the models, removing retires it, and every change is audited without the key.
Fictional keys and a fake provider read: no network.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.application import (
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
)
from ac_platform.identity.models import Session
from ac_platform.integrations.models import IntegrationSecret
from ac_platform.provider_hub import keys
from ac_platform.provider_hub.keys import ADDED, REMOVED, TESTED, FreeRead, ProviderKeys
from tests.database.test_conversation_reviews_postgresql import ReviewCase, run
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)
from tests.unit.http.test_conversation_learner_acquisition import _settings

PLATFORM = {"AC_INTEGRATIONS_SEAL_KEY": base64.urlsafe_b64encode(b"k" * 32).decode()}
FIRST = "fictional-gemini-key-0001"
SECOND = "fictional-gemini-key-0002"
SARVAM = "fictional-sarvam-key-9999"


def _settings_for(case: ReviewCase) -> Any:
    return _settings().model_copy(update={"operations_tenant_id": case.operations_tenant_id})


class FakeProvider:
    def __init__(self, status: int, document: Any = None) -> None:
        self.status, self.document, self.seen = status, document, []

    async def __call__(self, check: FreeRead, key: str) -> tuple[int, Any]:
        self.seen.append((check.url, key))
        return self.status, self.document


async def _clear(case: ReviewCase) -> None:
    """The test database outlives one test: start with no active provider key."""
    async with case.sessions() as database, database.begin():
        await database.execute(
            update(IntegrationSecret)
            .where(
                IntegrationSecret.purpose == "provider_key",
                IntegrationSecret.retired_at.is_(None),
            )
            .values(retired_at=datetime.now(UTC), retired_by="test:reset")
        )
    keys.LISTED.clear()


async def _do(
    case: ReviewCase,
    step: Any,
    *,
    environ: dict[str, str] | None = None,
    read: Any = None,
) -> Any:
    """One request's work in its own transaction, as the route runs it."""
    async with case.sessions() as database, database.begin():
        service = ProviderKeys(
            database,
            _settings_for(case),
            environ=PLATFORM if environ is None else environ,
            read=read or FakeProvider(200, {}),
        )
        return await step(service)


async def exercise(case: ReviewCase) -> None:
    await _clear(case)
    actor = case.admin_actor
    now = datetime.now(UTC)

    added = await _do(case, lambda s: s.add(actor, "gemini", f"  {FIRST}\n", now=now))
    assert added == {"provider": "gemini", "hint": "0001", "added_at": now.isoformat()}
    await _do(case, lambda s: s.add(actor, "gemini", SECOND, now=now))
    view = await _do(case, lambda s: s.view(actor))
    assert view["sealing"] is True and view["fresh_minutes"] == 10
    assert [(k["provider"], k["hint"], k["tested"]) for k in view["keys"]] == [
        ("gemini", "0002", None)
    ]

    # Sealed, never in clear; the first key retired, not deleted.
    async with case.sessions() as database:
        rows = (
            await database.scalars(
                select(IntegrationSecret)
                .where(IntegrationSecret.purpose == "provider_key")
                .order_by(IntegrationSecret.created_at)
            )
        ).all()
    mine = [row for row in rows if row.created_at == now and row.hint in {"0001", "0002"}]
    assert [row.retired_at is None for row in mine] == [False, True]
    assert all(FIRST not in row.sealed and SECOND not in row.sealed for row in mine)
    assert mine[0].retired_by == f"settings:person:{actor.person_id}"

    # The free check: works, lists the models, keeps only the count in the audit.
    provider = FakeProvider(
        200, {"models": [{"name": "models/gemini-a"}, {"name": "models/gemini-b"}]}
    )
    result = await _do(case, lambda s: s.test(actor, "gemini", now=now), read=provider)
    assert provider.seen == [(keys.FREE_READS["gemini"].url, SECOND)]
    assert (result["ok"], result["status"], result["models"]) == (True, 200, 2)
    assert result["words"] == "The key works: 2 models listed."
    assert keys.LISTED["gemini"][1] == ["gemini-a", "gemini-b"]
    refused = await _do(case, lambda s: s.test(actor, "gemini", now=now), read=FakeProvider(402))
    assert (refused["ok"], refused["fix"]) == (False, "console")
    assert "Out of credit" in refused["words"]
    view = await _do(case, lambda s: s.view(actor))
    assert view["keys"][0]["tested"]["ok"] is False and view["keys"][0]["tested"]["status"] == 402

    # A provider with no free check keeps its key untested.
    await _do(case, lambda s: s.add(actor, "sarvam", SARVAM, now=now))
    untested = await _do(case, lambda s: s.test(actor, "sarvam", now=now))
    assert untested["ok"] is None and "no free check" in untested["words"]

    # Removing retires it; testing then asks for a key.
    assert (await _do(case, lambda s: s.remove(actor, "gemini", now=now)))["removed"] == 1
    with pytest.raises(ConversationNotFound, match="Add a key first"):
        await _do(case, lambda s: s.test(actor, "gemini", now=now))
    assert "gemini" not in keys.LISTED

    # Nothing audited holds a key.
    async with case.sessions() as database:
        events = (
            await database.execute(
                select(AuditEvent.action, AuditEvent.payload).where(
                    AuditEvent.action.in_((ADDED, REMOVED, TESTED))
                )
            )
        ).all()
    assert {action for action, _ in events} == {ADDED, REMOVED, TESTED}
    for _, payload in events:
        assert all(secret not in str(payload) for secret in (FIRST, SECOND, SARVAM))

    # Bad input, unknown providers, no platform key, other workspaces: refused.
    with pytest.raises(ConversationError, match="no spaces"):
        await _do(case, lambda s: s.add(actor, "openai", "short", now=now))
    with pytest.raises(ConversationNotFound):
        await _do(case, lambda s: s.add(actor, "nobody", FIRST, now=now))
    with pytest.raises(ConversationError, match="can't be sealed"):
        await _do(case, lambda s: s.add(actor, "openai", FIRST, now=now), environ={})
    with pytest.raises(ConversationDenied):
        await _do(case, lambda s: s.add(case.foreign_actor, "openai", FIRST, now=now))


async def stale_sign_in(case: ReviewCase) -> None:
    await _clear(case)
    async with case.sessions() as database, database.begin():
        await database.execute(
            update(Session)
            .where(Session.id == case.admin_actor.session_id)
            .values(created_at=datetime.now(UTC) - timedelta(minutes=20))
        )
    with pytest.raises(ConversationDenied, match="Sign in again"):
        await _do(
            case,
            lambda s: s.add(case.admin_actor, "openai", FIRST, now=datetime.now(UTC)),
        )


def test_provider_keys_are_sealed_tested_and_retired(review_case: ReviewCase) -> None:
    run(exercise(review_case))


def test_a_provider_key_needs_a_sign_in_within_ten_minutes(review_case: ReviewCase) -> None:
    run(stale_sign_in(review_case))
