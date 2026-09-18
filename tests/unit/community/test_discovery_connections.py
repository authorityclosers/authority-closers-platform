from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.community import application as community_module
from ac_platform.community.application import (
    CommunityApplication,
    CommunityTargetUnavailable,
    DiscoveryUsernameRequired,
)
from ac_platform.community.models import (
    CohorvaPublicProfile,
    CommunityConnection,
    CommunityConnectionEvent,
    CommunityDiscoveryPreference,
)
from ac_platform.kernel.authz import ActorContext


class FakeResult:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []

    def mappings(self) -> FakeResult:
        return self

    def first(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.rows)


class FakeDatabase:
    def __init__(
        self,
        *,
        scalars: list[object] | None = None,
        rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.scalars = list(scalars or [])
        self.rows = rows or []
        self.added: list[object] = []

    def get_transaction(self) -> object:
        return SimpleNamespace(
            sync_transaction=SimpleNamespace(origin=SessionTransactionOrigin.BEGIN)
        )

    async def scalar(self, _statement: object) -> object:
        return self.scalars.pop(0) if self.scalars else None

    async def execute(self, _statement: object) -> FakeResult:
        return FakeResult(self.rows)

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        return None

    @asynccontextmanager
    async def begin_nested(self):  # type: ignore[no-untyped-def]
        yield


class FakeAudit:
    async def append_for_actor(self, *_args: object, **_kwargs: object) -> None:
        return None


@pytest.fixture(autouse=True)
def fake_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(community_module, "AuditRepository", lambda _database: FakeAudit())


def actor() -> ActorContext:
    return ActorContext(uuid4(), uuid4(), uuid4())


def identity(current: ActorContext) -> CohorvaPublicProfile:
    return CohorvaPublicProfile(
        person_id=current.person_id,
        username="learner_7",
        claimed_session_id=current.session_id,
        claim_source="account_claim",
        legacy_profile_count=0,
    )


def public_row(username: str = "other_learner") -> dict[str, object]:
    return {
        "person_id": uuid4(),
        "username": username,
        "public_display_name": "Chosen display",
        "avatar_asset_id": None,
        "leaderboard_opted_in": False,
        "practice_xp_total": None,
    }


@pytest.mark.asyncio
async def test_discovery_is_private_by_default_and_requires_username_to_enable() -> None:
    current = actor()
    database = FakeDatabase(scalars=[None, None])
    result = await CommunityApplication(database).discovery_profile(current)

    assert result == {
        "username": None,
        "discoverable": False,
        "public_display_name": None,
        "avatar_asset_id": None,
        "revision": 0,
    }

    with pytest.raises(DiscoveryUsernameRequired):
        await CommunityApplication(FakeDatabase(scalars=[None, None])).set_discovery(
            current,
            discoverable=True,
            public_display_name="Chosen display",
            avatar_asset_id=None,
            expected_revision=0,
        )


@pytest.mark.asyncio
async def test_discovery_update_stores_only_chosen_surface() -> None:
    current = actor()
    database = FakeDatabase(scalars=[identity(current), None])
    result = await CommunityApplication(database).set_discovery(
        current,
        discoverable=True,
        public_display_name=" Chosen display ",
        avatar_asset_id=None,
        expected_revision=0,
    )

    preference = next(
        row for row in database.added if isinstance(row, CommunityDiscoveryPreference)
    )
    assert preference.discoverable is True
    assert preference.public_display_name == "Chosen display"
    assert preference.revision == 1
    assert "email" not in repr(result)
    assert "course" not in repr(result)


@pytest.mark.asyncio
async def test_private_profiles_are_not_resolvable_and_requests_record_mutual_state() -> None:
    current = actor()
    missing = FakeDatabase(rows=[])
    with pytest.raises(CommunityTargetUnavailable):
        await CommunityApplication(missing)._public_candidate(current, "hidden_user")

    row = public_row()
    database = FakeDatabase(rows=[row], scalars=[None])
    result = await CommunityApplication(database).request_connection(current, "other_learner")
    connection = next(row for row in database.added if isinstance(row, CommunityConnection))
    event = next(row for row in database.added if isinstance(row, CommunityConnectionEvent))

    assert result == {"username": "other_learner", "state": "pending", "incoming": False}
    assert connection.state == "pending"
    assert event.action == "requested"
    assert "email" not in repr(result)


@pytest.mark.asyncio
async def test_incoming_request_requires_recipient_accept_or_decline() -> None:
    current = actor()
    target = public_row()
    connection = CommunityConnection(
        tenant_id=current.tenant_id,
        person_a_id=min(current.person_id, target["person_id"]),
        person_b_id=max(current.person_id, target["person_id"]),
        requested_by_person_id=target["person_id"],
        state="pending",
        revision=1,
    )
    database = FakeDatabase(rows=[target], scalars=[None, connection])
    result = await CommunityApplication(database).respond_connection(
        current, "other_learner", accept=True
    )

    assert result["state"] == "accepted"
    assert connection.state == "accepted"
    assert any(
        isinstance(row, CommunityConnectionEvent) and row.action == "accepted"
        for row in database.added
    )
