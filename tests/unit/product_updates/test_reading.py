"""Exercise reading queries and account receipts against the portable store."""

from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.product_updates.models import Notification, ProductUpdate, UpdateSeen
from ac_platform.product_updates.reading import FEATURE_REGISTRY, ProductUpdatesReading
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.unit.conversation_intelligence.test_activation_contract import _bundle
from tests.unit.conversation_intelligence.test_internal_tester import _approval

NOW = datetime(2026, 10, 5, tzinfo=UTC)


class AsyncDatabase:
    """Run the same SQL through SQLite without requiring an async SQLite driver."""

    def __init__(self, session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)

    async def scalars(self, statement):
        return self.session.scalars(statement)

    async def scalar(self, statement):
        return self.session.scalar(statement)

    def get_bind(self):
        return self.session.get_bind()


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    model_metadata().create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def person(database):
    row = Person(email=f"fictional-{uuid4().hex}@example.test", email_verified_at=NOW)
    database.add(row)
    database.flush()
    return ActorContext(person_id=row.id, session_id=uuid4(), tenant_id=None)


def note(database, key, **changes):
    values = dict(
        id=uuid4(),
        note_key=key,
        version=1,
        release_id="release-one",
        note_date=date(2026, 10, 5),
        title="Fictional update",
        items=["A fictional change."],
        status="published",
        published_at=NOW,
        created_at=NOW - timedelta(days=2),
        created_by="seed",
    )
    row = ProductUpdate(**(values | changes))
    database.add(row)
    database.flush()
    return row


def reader(database, actor, **kwargs):
    return ProductUpdatesReading(
        cast(AsyncSession, AsyncDatabase(database)),
        actor,
        environment=kwargs.pop("environment", "staging"),
        **kwargs,
    )


@pytest.mark.parametrize(
    "role,registered,active,expected",
    [
        ("owner", True, True, 2),
        ("admin", True, True, 2),
        ("member", True, True, 1),
        ("admin", False, True, 1),
        ("admin", True, False, 1),
    ],
)
async def test_everyone_and_registered_org_admins(database, role, registered, active, expected):
    actor = person(database)
    tenant = Tenant(slug=uuid4().hex, name="Fictional organisation")
    database.add(tenant)
    database.flush()
    database.add(
        Membership(
            person_id=actor.person_id,
            tenant_id=tenant.id,
            role=role,
            status="active" if active else "inactive",
            ended_at=None if active else NOW,
        )
    )
    if registered:
        database.add(
            Organisation(
                tenant_id=tenant.id,
                creation_command_id=uuid4(),
                domain_verification_token="t" * 43,
            )
        )
    note(database, "everyone")
    note(database, "admins", audience="org_admins")
    # The registered admin need not currently select that organisation.
    result = await reader(database, actor).updates()
    assert result["unseen_count"] == expected
    assert len(result["updates"]) == expected


@pytest.mark.parametrize(
    "policy_kind,expected", [("tester", 2), ("neighbor", 1), (None, 1), ("expired", 1)]
)
async def test_testers_use_live_internal_tester_policy(database, policy_kind, expected):
    actor = person(database)
    tenant = Tenant(slug=uuid4().hex, name="Fictional personal workspace")
    database.add(tenant)
    database.flush()
    database.add(Membership(person_id=actor.person_id, tenant_id=tenant.id, role="learner"))
    actor = ActorContext(actor.person_id, actor.session_id, tenant.id)
    account = database.get(Person, actor.person_id)
    epoch = int(datetime.now(UTC).timestamp())
    bundle = _bundle(
        issued_at_epoch=epoch - 60,
        expires_at_epoch=epoch - 1 if policy_kind == "expired" else epoch + 3600,
        stages=(),
        internal_tester_accounts=(
            _approval(account.email if policy_kind != "neighbor" else "neighbor@example.test"),
        ),
    )
    policy = None if policy_kind is None else InternalTesterPolicy(lambda: bundle, "test")
    note(database, "everyone")
    note(database, "testers", audience="testers")
    assert (await reader(database, actor, tester_policy=policy).updates())[
        "unseen_count"
    ] == expected


async def test_unknown_feature_hides_note_and_registered_resolver_can_admit(database, monkeypatch):
    actor = person(database)
    note(database, "feature", feature_key="fictional-feature")
    assert (await reader(database, actor).updates())["updates"] == []

    async def feature(_database, recipient):
        return recipient.person_id == actor.person_id

    monkeypatch.setitem(FEATURE_REGISTRY, "fictional-feature", feature)
    assert (await reader(database, actor).updates())["unseen_count"] == 1
    assert (await reader(database, person(database)).updates())["updates"] == []


@pytest.mark.parametrize(
    "environment,version,draft",
    [
        ("staging", 2, False),
        ("production", 2, False),
        ("test", 2, False),
        ("local", 2, False),
        ("development", 4, True),
    ],
)
async def test_version_selection_keeps_lineage_publication_order(
    database, environment, version, draft
):
    actor = person(database)
    old = note(
        database, "older", published_at=NOW - timedelta(days=4), created_at=NOW - timedelta(days=5)
    )
    revised = note(database, "older", version=2, supersedes_id=old.id, published_at=NOW)
    approved = note(
        database, "older", version=3, supersedes_id=revised.id, status="approved", published_at=None
    )
    note(database, "older", version=4, supersedes_id=approved.id, status="draft", published_at=None)
    note(database, "newer", published_at=NOW - timedelta(days=1))
    note(database, "never-published", status="approved", published_at=None)
    results = await reader(database, actor, environment=environment).updates()
    older = next(item for item in results["updates"] if item["key"] == "older")
    assert (older["version"], older["draft"]) == (version, draft)
    assert results["updates"][-1]["key"] == "older"
    assert len(results["updates"]) == (3 if environment == "development" else 2)
    filtered = await reader(database, actor, environment=environment).updates(
        NOW - timedelta(days=2)
    )
    assert [item["key"] for item in filtered["updates"]] == ["newer"]
    assert filtered["unseen_count"] == len(results["updates"])


async def test_seen_is_idempotent_account_owned_and_ignores_invisible_keys(database):
    actor, neighbor = person(database), person(database)
    note(database, "visible")
    note(database, "hidden", feature_key="unknown")
    service = reader(database, actor)
    for _ in range(2):
        assert await service.mark_seen(["visible", "visible", "hidden", "unknown"]) == {
            "unseen_count": 0
        }
    database.commit()
    second_session = ActorContext(actor.person_id, uuid4(), uuid4())
    with Session(database.get_bind()) as another_database:
        assert (await reader(another_database, second_session).updates())["unseen_count"] == 0
        assert (await reader(another_database, neighbor).updates())["unseen_count"] == 1
    assert database.scalars(select(UpdateSeen.note_key)).all() == ["visible"]


async def test_release_grouping_and_event_read_are_recipient_owned(database):
    actor, neighbor = person(database), person(database)
    note(database, "first", published_at=NOW - timedelta(days=1))
    note(database, "second")
    note(database, "single", release_id="release-two", published_at=NOW - timedelta(days=2))
    note(database, "hidden", feature_key="unknown")
    events = [
        Notification(
            person_id=recipient.person_id,
            kind="report_ready",
            dedupe_key=uuid4().hex,
            title="Fictional report",
            body="Ready to read.",
            href="/reports/test",
            urgent=True,
            created_at=NOW + timedelta(hours=1),
        )
        for recipient in (actor, neighbor)
    ]
    database.add_all(events)
    database.flush()
    service = reader(database, actor)
    result = await service.notifications()
    assert result["unread_count"] == 3
    assert result["notifications"][0]["id"] == str(events[0].id)
    group = result["notifications"][1]
    assert (group["count"], group["title"], group["read"]) == (2, "2 new updates", False)
    assert result["notifications"][2]["title"] == "1 new update"
    await service.mark_seen(["first"])
    assert not (await service.notifications())["notifications"][1]["read"]
    assert await service.mark_read([str(events[1].id), "updates:unknown", "garbage"]) == {
        "unread_count": 3
    }
    ids = [str(events[0].id), "updates:release-one"]
    assert await service.mark_read(ids) == {"unread_count": 1}
    database.refresh(events[0])
    read_at = events[0].read_at
    assert await service.mark_read(ids) == {"unread_count": 1}
    database.refresh(events[0])
    database.refresh(events[1])
    assert events[0].read_at == read_at and events[1].read_at is None
    assert database.scalars(select(UpdateSeen.note_key).order_by(UpdateSeen.note_key)).all() == [
        "first",
        "second",
    ]


async def test_feed_limits_do_not_truncate_badge_counts_or_release_acknowledgements(database):
    actor = person(database)
    for index in range(105):
        note(database, f"note-{index:03}", release_id="bulk")
    database.add_all(
        [
            Notification(
                person_id=actor.person_id,
                kind="invite_received",
                dedupe_key=str(index),
                title="Fictional invitation",
                body="An invitation.",
                href="/organisation",
                created_at=NOW + timedelta(hours=index + 1),
            )
            for index in range(55)
        ]
    )
    database.flush()
    service = reader(database, actor)
    assert len((await service.updates())["updates"]) == 100
    assert (await service.updates())["unseen_count"] == 105
    result = await service.notifications()
    assert len(result["notifications"]) == 50 and result["unread_count"] == 56
    assert await service.mark_read(["updates:bulk"]) == {"unread_count": 55}
    assert len(database.scalars(select(UpdateSeen)).all()) == 105


@pytest.mark.parametrize("environment", ["staging", "development"])
async def test_read_all_covers_full_history_and_preserves_other_accounts(database, environment):
    actor, neighbor = person(database), person(database)
    for index in range(105):
        note(database, f"bulk-{index}", release_id=f"release-{index}")
    note(database, "hidden-feature", feature_key="unknown")
    note(database, "hidden-audience", audience="org_admins")
    note(database, "hidden-tester", audience="testers")
    note(database, "draft", status="draft", published_at=None)
    prior_read_at = NOW - timedelta(hours=2)
    events = [
        Notification(
            person_id=recipient.person_id,
            kind="invite_received",
            dedupe_key=str(index),
            title="Fictional invitation",
            body="An invitation.",
            href="/organisation",
            created_at=NOW + timedelta(hours=index + 1),
            read_at=prior_read_at if index == 0 else None,
        )
        for recipient in (actor, neighbor)
        for index in range(55)
    ]
    database.add_all(events)
    database.flush()
    service = reader(database, actor, environment=environment)
    await service.mark_seen(["bulk-0"])
    original_seen_at = database.scalar(
        select(UpdateSeen.seen_at).where(UpdateSeen.note_key == "bulk-0")
    )
    before = await service.notifications()
    assert len(before["notifications"]) == 50
    assert before["unread_count"] == (159 if environment == "development" else 158)

    assert await service.mark_all_read() == {"unread_count": 0}
    database.commit()
    second_session = ActorContext(actor.person_id, uuid4(), None)
    with Session(database.get_bind()) as another_database:
        assert (
            await reader(another_database, second_session, environment=environment).notifications()
        )["unread_count"] == 0
        assert (await reader(another_database, neighbor, environment=environment).notifications())[
            "unread_count"
        ] == (160 if environment == "development" else 159)
    timestamps = database.execute(select(Notification.id, Notification.read_at)).all()
    assert await service.mark_all_read() == {"unread_count": 0}
    assert database.execute(select(Notification.id, Notification.read_at)).all() == timestamps
    assert (
        database.scalar(select(UpdateSeen.seen_at).where(UpdateSeen.note_key == "bulk-0"))
        == original_seen_at
    )
    receipts = database.scalars(select(UpdateSeen.note_key)).all()
    assert len(receipts) == (106 if environment == "development" else 105)
    assert not {"hidden-feature", "hidden-audience", "hidden-tester"}.intersection(receipts)
    database.refresh(events[0])
    assert events[0].read_at == prior_read_at.replace(tzinfo=None)

    # A later event and release remain unread; the command creates no future preference.
    note(database, "later", release_id="later-release", published_at=NOW + timedelta(days=1))
    database.add(
        Notification(
            person_id=actor.person_id,
            kind="report_ready",
            dedupe_key="later",
            title="Fictional later report",
            body="Ready to read.",
            href="/analysis/calls/fictional",
            created_at=NOW + timedelta(days=1),
        )
    )
    database.flush()
    assert (await service.notifications())["unread_count"] == 2
