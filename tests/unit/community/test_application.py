from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.community import application as community_module
from ac_platform.community.application import (
    CommunityApplication,
    CommunityError,
    CommunityRevisionConflict,
    UsernameAlreadyClaimed,
    UsernameUnavailable,
)
from ac_platform.community.models import (
    AcademyLeaderboardPreference,
    CohorvaPublicProfile,
)
from ac_platform.kernel.authz import ActorContext


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]] | None = None, rowcount: int = 1) -> None:
        self.rows = rows or []
        self.rowcount = rowcount

    def mappings(self) -> list[dict[str, Any]]:
        return self.rows


class FakeDatabase:
    def __init__(
        self,
        scalars: list[Any] | None = None,
        *,
        explicit_transaction: bool = True,
    ) -> None:
        self.scalars = list(scalars or [])
        self.added: list[Any] = []
        self.executed: list[Any] = []
        self.flush_error: Exception | None = None
        self.result = FakeResult()
        self.explicit_transaction = explicit_transaction

    def get_transaction(self) -> Any:
        if not self.explicit_transaction:
            return None
        return SimpleNamespace(
            sync_transaction=SimpleNamespace(origin=SessionTransactionOrigin.BEGIN)
        )

    async def scalar(self, _statement: Any) -> Any:
        return self.scalars.pop(0) if self.scalars else None

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error

    @asynccontextmanager
    async def begin_nested(self):  # type: ignore[no-untyped-def]
        yield

    async def execute(self, statement: Any) -> FakeResult:
        self.executed.append(statement)
        return self.result


class FakeAuditRepository:
    events: list[dict[str, Any]] = []

    def __init__(self, _database: Any) -> None:
        pass

    async def append_for_actor(self, _actor: ActorContext, **event: Any) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def fake_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAuditRepository.events = []
    monkeypatch.setattr(community_module, "AuditRepository", FakeAuditRepository)


def actor() -> ActorContext:
    return ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=uuid4())


def identity(current: ActorContext, username: str = "learner_7") -> CohorvaPublicProfile:
    return CohorvaPublicProfile(
        person_id=current.person_id,
        username=username,
        claimed_session_id=current.session_id,
        claim_source="account_claim",
        legacy_profile_count=0,
    )


def preference(
    current: ActorContext, *, opted_in: bool = False, revision: int = 1
) -> AcademyLeaderboardPreference:
    assert current.tenant_id is not None
    return AcademyLeaderboardPreference(
        tenant_id=current.tenant_id,
        person_id=current.person_id,
        leaderboard_opted_in=opted_in,
        revision=revision,
    )


@pytest.mark.asyncio
async def test_mutations_require_an_explicit_caller_owned_transaction() -> None:
    current = actor()
    existing = preference(current)
    claim_database = FakeDatabase([None], explicit_transaction=False)
    with pytest.raises(CommunityError, match="caller-owned transaction"):
        await CommunityApplication(claim_database).claim_username(current, "learner_7")  # type: ignore[arg-type]
    assert len(claim_database.scalars) == 1

    preference_database = FakeDatabase([identity(current), existing], explicit_transaction=False)
    with pytest.raises(CommunityError, match="caller-owned transaction"):
        await CommunityApplication(preference_database).set_leaderboard_opt_in(  # type: ignore[arg-type]
            current, opted_in=True, expected_revision=1
        )
    assert len(preference_database.scalars) == 2


@pytest.mark.asyncio
async def test_claim_username_creates_one_global_identity_without_academy() -> None:
    current = actor()
    current = ActorContext(current.person_id, current.session_id, None)
    database = FakeDatabase([None])

    result = await CommunityApplication(database).claim_username(current, " Learner_7 ")  # type: ignore[arg-type]

    row = database.added[0]
    assert isinstance(row, CohorvaPublicProfile)
    assert (row.person_id, row.username, row.claimed_session_id) == (
        current.person_id,
        "learner_7",
        current.session_id,
    )
    assert row.claim_source == "account_claim"
    assert result["leaderboard_opted_in"] is False
    assert result["revision"] == 0
    assert FakeAuditRepository.events == []


@pytest.mark.asyncio
async def test_claim_username_is_idempotent_but_does_not_overwrite_identity() -> None:
    current = actor()
    existing = identity(current)
    same = await CommunityApplication(FakeDatabase([existing, None])).claim_username(  # type: ignore[arg-type]
        current, "LEARNER_7"
    )
    assert same["username"] == "learner_7"
    assert FakeAuditRepository.events == []

    with pytest.raises(UsernameAlreadyClaimed):
        await CommunityApplication(FakeDatabase([existing])).claim_username(  # type: ignore[arg-type]
            current, "another_name"
        )
    assert existing.username == "learner_7"


@pytest.mark.asyncio
async def test_selected_academy_claim_keeps_global_identity_and_tenant_audit() -> None:
    current = actor()
    database = FakeDatabase([None, None])

    result = await CommunityApplication(database).claim_username(current, "learner_7")  # type: ignore[arg-type]

    assert result == {
        "username": "learner_7",
        "leaderboard_opted_in": False,
        "revision": 0,
        "leaderboard_policy": result["leaderboard_policy"],
    }
    assert FakeAuditRepository.events == [
        {
            "action": "community.username_claimed",
            "resource_type": "community_public_profile",
            "resource_id": current.person_id,
            "payload": {"username": "learner_7", "scope": "global"},
        }
    ]


@pytest.mark.asyncio
async def test_database_uniqueness_loss_returns_generic_unavailable() -> None:
    database = FakeDatabase([None, None])
    database.flush_error = IntegrityError("insert", {}, RuntimeError("duplicate"))

    with pytest.raises(UsernameUnavailable, match="unavailable"):
        await CommunityApplication(database).claim_username(actor(), "learner_7")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_opt_in_is_revision_guarded_and_withdrawal_is_audited() -> None:
    current = actor()
    existing = preference(current, opted_in=True, revision=4)
    database = FakeDatabase([identity(current), existing])

    result = await CommunityApplication(database).set_leaderboard_opt_in(  # type: ignore[arg-type]
        current, opted_in=False, expected_revision=4
    )

    assert result["leaderboard_opted_in"] is False
    assert result["revision"] == 5
    assert FakeAuditRepository.events[0]["action"] == "community.leaderboard_withdrawn"
    assert FakeAuditRepository.events[0]["payload"] == {
        "policy_version": "all_time_practice_xp_v1",
        "profile_revision": 5,
    }

    stale = preference(current, opted_in=False, revision=5)
    with pytest.raises(CommunityRevisionConflict):
        await CommunityApplication(FakeDatabase([identity(current), stale])).set_leaderboard_opt_in(  # type: ignore[arg-type]
            current, opted_in=True, expected_revision=4
        )


@pytest.mark.asyncio
async def test_first_academy_opt_in_creates_separate_revisioned_preference() -> None:
    current = actor()
    database = FakeDatabase([identity(current), None])

    result = await CommunityApplication(database).set_leaderboard_opt_in(  # type: ignore[arg-type]
        current, opted_in=True, expected_revision=0
    )

    row = database.added[0]
    assert isinstance(row, AcademyLeaderboardPreference)
    assert (row.tenant_id, row.person_id, row.leaderboard_opted_in, row.revision) == (
        current.tenant_id,
        current.person_id,
        True,
        1,
    )
    assert result["username"] == "learner_7"
    assert result["leaderboard_opted_in"] is True
    assert result["revision"] == 1


@pytest.mark.asyncio
async def test_leaderboard_query_uses_competition_rank_and_public_fields_only() -> None:
    current = actor()
    other = uuid4()
    database = FakeDatabase()
    database.result = FakeResult(
        [
            {
                "person_id": current.person_id,
                "username": "alex",
                "xp_total": 90,
                "rank": 1,
            },
            {
                "person_id": other,
                "username": "sam",
                "xp_total": 90,
                "rank": 1,
            },
        ]
    )
    result = await CommunityApplication(database).leaderboard(  # type: ignore[arg-type]
        current, limit=25, cursor=None
    )

    assert result["items"] == [
        {"rank": 1, "username": "alex", "xp_total": 90, "is_current_learner": True},
        {"rank": 1, "username": "sam", "xp_total": 90, "is_current_learner": False},
    ]
    assert "email" not in repr(result)
    assert "analytics" not in repr(database.executed[0]).lower()
    compiled = str(database.executed[0])
    assert "rank() OVER" in compiled
    assert "academy_leaderboard_preferences.leaderboard_opted_in" in compiled
    assert "community_public_profiles.username" in compiled
    assert "practice_reward_claims.xp >" in compiled
