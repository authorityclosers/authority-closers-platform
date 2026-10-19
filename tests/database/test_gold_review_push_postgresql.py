"""Gold review phone alerts (19 Oct): one push per new assignment, ids and a count only."""

from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.gold_review_job import assign_saved_reviews
from ac_platform.conversation_intelligence.gold_review_models import GoldAssignment
from ac_platform.conversation_intelligence.gold_reviews import GoldReviews
from ac_platform.lead_desk.contracts import DeviceCommand
from ac_platform.lead_desk.models import LeadDevice
from ac_platform.lead_desk.review_push import ACTION, ReviewAlert, register_phone, tick
from ac_platform.lead_desk.store import token_digest
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_reviews_postgresql import ReviewCase, _service, run
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)
from tests.database.test_gold_reviews_postgresql import prepare


class FakeFcm:
    """Records what would go to Google; tokens in ``gone`` are dead phones."""

    def __init__(self, gone: tuple[str, ...] = ()) -> None:
        self.sent: list[tuple[str, dict[str, str]]] = []
        self.gone = set(gone)

    async def send(self, client, token, data):
        self.sent.append((token, dict(data)))
        return "gone" if token in self.gone else "sent"


def _device(case: ReviewCase, person_id: UUID, token: str) -> LeadDevice:
    now = case.prepared.state.now
    return LeadDevice(
        id=uuid4(),
        tenant_id=case.prepared.state.tenant_id,
        person_id=person_id,
        platform="android",
        token=token,
        token_sha256=token_digest(token),
        app_version="0.3.test",
        created_at=now,
        last_seen_at=now,
    )


async def _alerts(case: ReviewCase) -> list[AuditEvent]:
    async with case.sessions() as db:
        return list(
            (
                await db.scalars(
                    select(AuditEvent).where(AuditEvent.action == ACTION).order_by(AuditEvent.id)
                )
            ).all()
        )


@pytest.fixture(scope="module")
def push_case(review_case):
    assignment_id, review_id = run(prepare(review_case))
    return review_case, assignment_id, review_id


def test_alert_data_is_ids_and_a_count() -> None:
    first, second, third = (UUID(int=n) for n in (1, 2, 3))
    one = ReviewAlert(reviewer_id=UUID(int=9), assignments=[first], waiting=4)
    assert one.data() == {
        "type": "gold_review",
        "kind": "one",
        "assignment": str(first),
        "alerts": "1",
        "count": "4",
    }
    # Several in one pass (a first designation) are one alert that opens the list.
    many = ReviewAlert(reviewer_id=UUID(int=9), assignments=[first, second, third], waiting=12)
    assert many.data() == {
        "type": "gold_review",
        "kind": "many",
        "assignment": str(third),
        "alerts": "3",
        "count": "12",
    }


def test_one_push_per_new_assignment_to_the_reviewers_phones_only(push_case) -> None:
    case, assignment, _ = push_case
    reviewer = case.reviewer_actor.person_id

    async def exercise():
        async with case.sessions() as db:
            created = (await db.get(GoldAssignment, assignment)).created_at
        fcm = FakeFcm(gone=("reviewer-old-phone",))
        async with httpx.AsyncClient() as client:
            # No phone yet: nothing sent, nothing recorded, so a phone added soon still hears.
            assert await tick(case.sessions, fcm, client, now=created) == 0
            assert fcm.sent == [] and await _alerts(case) == []
            async with case.sessions() as db, db.begin():
                db.add(_device(case, reviewer, "reviewer-phone"))
                db.add(_device(case, reviewer, "reviewer-old-phone"))
                db.add(_device(case, case.source_actor.person_id, "seller-phone"))
            # Older than two hours: a phone that registers late is not flooded.
            assert await tick(case.sessions, fcm, client, now=created + timedelta(hours=3)) == 0
            assert fcm.sent == [] and await _alerts(case) == []
            later = created + timedelta(seconds=30)
            assert await tick(case.sessions, fcm, client, now=later) == 1
            data = {
                "type": "gold_review",
                "kind": "one",
                "assignment": str(assignment),
                "alerts": "1",
                "count": "1",
            }
            # The reviewer's phones only; never the seller whose call it is.
            assert sorted(fcm.sent, key=lambda sent: sent[0]) == [
                ("reviewer-old-phone", data),
                ("reviewer-phone", data),
            ]
            # Never twice.
            assert await tick(case.sessions, fcm, client, now=later + timedelta(minutes=1)) == 0
            assert len(fcm.sent) == 2
        alerts = await _alerts(case)
        assert [(a.resource_type, a.resource_id, a.actor_type) for a in alerts] == [
            ("conversation_review_assignment", str(assignment), "system")
        ]
        assert alerts[0].tenant_id == case.prepared.state.tenant_id
        assert alerts[0].payload == {"reviewer_id": str(reviewer), "sender": "gold-review-push/1"}
        async with case.sessions() as db:
            # A dead phone is forgotten; the live one stays.
            tokens = set(
                (
                    await db.scalars(
                        select(LeadDevice.token).where(LeadDevice.person_id == reviewer)
                    )
                ).all()
            )
            assert tokens == {"reviewer-phone"}

    run(exercise())


def test_a_revoked_reviewer_gets_no_alert(push_case) -> None:
    case, _, _ = push_case
    other = case.other_reviewer_actor.person_id
    email = "reviewer-" + other.hex + "@example.test"
    now = case.prepared.state.now

    async def exercise():
        async with case.sessions() as db, db.begin():
            await GoldReviews(_service(db, case)).designate(case.admin_actor, email, True)
            assert await assign_saved_reviews(db, case.operations_tenant_id, now) == 1
            db.add(_device(case, other, "other-reviewer-phone"))
        async with case.sessions() as db, db.begin():
            await GoldReviews(_service(db, case)).designate(case.admin_actor, email, False)
        before = len(await _alerts(case))
        fcm = FakeFcm()
        async with httpx.AsyncClient() as client:
            assert await tick(case.sessions, fcm, client, now=now + timedelta(seconds=30)) == 0
        assert fcm.sent == [] and len(await _alerts(case)) == before

    run(exercise())


def test_a_reviewer_turns_alerts_on_from_review(push_case) -> None:
    """The /review card: no Leads or organisation workspace needed, never lead alerts."""
    case, _, _ = push_case
    reviewer = case.reviewer_actor.person_id
    calls = case.prepared.state.tenant_id
    operations = case.operations_tenant_id
    now = case.prepared.state.now
    phone = DeviceCommand(token="review-card-phone-" + "a" * 24, app_version="0.3.test")

    async def kept_in() -> set:
        async with case.sessions() as db:
            return set(
                (
                    await db.scalars(
                        select(LeadDevice.tenant_id).where(
                            LeadDevice.token_sha256 == token_digest(phone.token),
                            LeadDevice.person_id == reviewer,
                        )
                    )
                ).all()
            )

    async def exercise():
        async with case.sessions() as db, db.begin():
            # Someone who is not a standing reviewer keeps no phone here.
            with pytest.raises(ConversationDenied):
                await register_phone(
                    db,
                    case.source_actor.person_id,
                    phone,
                    now,
                    quiet=(operations, None),
                    current=calls,
                )
        async with case.sessions() as db, db.begin():
            # Their only workspace is used when no quiet one is theirs.
            assert await register_phone(
                db, reviewer, phone, now, quiet=(operations, None), current=None
            )
        assert await kept_in() == {calls}
        async with case.sessions() as db, db.begin():
            if await db.get(Membership, (operations, reviewer)) is None:
                db.add(
                    Membership(
                        tenant_id=operations, person_id=reviewer, role="learner", status="active"
                    )
                )
        async with case.sessions() as db, db.begin():
            # A workspace where Leads don't run comes before the current one.
            assert await register_phone(
                db, reviewer, phone, now, quiet=(operations, None), current=calls
            )
        assert await kept_in() == {calls, operations}

    run(exercise())
