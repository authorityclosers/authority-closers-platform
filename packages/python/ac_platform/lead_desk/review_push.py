"""Phone alerts for gold review: a new Report is ready for a gold reviewer (owner, 19 Oct).

The gold reader (``conversation_intelligence.gold_review_job``) stays provider-free:
it only writes ``conversation_gold_assignments``. This separate, bounded reader runs
in the API beside the Lead Desk sender (``push.attach``). It finds gold assignments
made in the last two hours that were not alerted yet and sends an FCM data message to
the reviewer's phones: the ``LeadDevice`` tokens of that person, in any workspace.

A message carries ids and a count only, never call content:
``{type: gold_review, kind, assignment, alerts, count}``. The app reads the words on
the reviewer's own session (``GET /v1/sales-xray/review/badge``) and opens
``/review#call=<assignment>``.

Each alerted assignment gets one append-only audit event,
``conversation.gold_review_alerted``, in the call's workspace chain (where its
``conversation.gold_review_assigned`` event already is); that is also how the reader
knows what was sent, so no table changes. Assignments made in one reader pass (a
first designation can make twenty) become one alert, "12 Reports to review", which
opens the review list. Nothing older than two hours is sent, so a phone that
registers late is not flooded. Off until the FCM settings exist (``push.config``).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import String, cast, delete, exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.gold_review_account import badge
from ac_platform.conversation_intelligence.gold_review_models import GoldAssignment, GoldReviewer
from ac_platform.conversation_intelligence.models import (
    ConversationRecording,
    ConversationReviewAssignment,
    ConversationReviewRevocation,
)
from ac_platform.lead_desk.models import LeadDevice
from ac_platform.lead_desk.push import BATCH, WINDOW, Fcm
from ac_platform.lead_desk.store import token_digest

ACTION = "conversation.gold_review_alerted"
RESOURCE = "conversation_review_assignment"
_LOCK = (1802, 1264)  # one review sender across API processes and slots


@dataclass(slots=True)
class ReviewAlert:
    reviewer_id: UUID
    assignments: list[UUID] = field(default_factory=list)
    waiting: int = 0
    tokens: list[str] = field(default_factory=list)

    def data(self) -> dict[str, str]:
        """The FCM data: ids and a count only, never anything about the call."""
        return {
            "type": "gold_review",
            "kind": "one" if len(self.assignments) == 1 else "many",
            "assignment": str(self.assignments[-1]),
            "alerts": str(len(self.assignments)),
            "count": str(self.waiting),
        }


def _alerted() -> Any:
    return exists().where(
        AuditEvent.tenant_id == ConversationReviewAssignment.tenant_id,
        AuditEvent.resource_type == RESOURCE,
        AuditEvent.resource_id == cast(GoldAssignment.assignment_id, String),
        AuditEvent.action == ACTION,
    )


async def collect(database: AsyncSession, now: datetime) -> list[ReviewAlert]:
    """Finds the review alerts to send now and records them (the caller commits)."""
    rows = (
        await database.execute(
            select(
                GoldAssignment.assignment_id,
                GoldAssignment.reviewer_id,
                ConversationReviewAssignment.tenant_id,
            )
            .join(
                ConversationReviewAssignment,
                ConversationReviewAssignment.id == GoldAssignment.assignment_id,
            )
            .join(GoldReviewer, GoldReviewer.person_id == GoldAssignment.reviewer_id)
            .join(ConversationRecording, ConversationRecording.id == GoldAssignment.recording_id)
            .where(
                GoldAssignment.created_at > now - WINDOW,
                GoldAssignment.created_at <= now,
                GoldReviewer.revoked_at.is_(None),
                ConversationReviewAssignment.expires_at > now,
                ConversationRecording.deleted_at.is_(None),
                ~exists().where(
                    ConversationReviewRevocation.assignment_id == GoldAssignment.assignment_id
                ),
                exists().where(LeadDevice.person_id == GoldAssignment.reviewer_id),
                ~_alerted(),
            )
            .order_by(GoldAssignment.created_at, GoldAssignment.assignment_id)
            .limit(BATCH)
        )
    ).all()
    if not rows:
        return []
    audit = AuditRepository(database)
    alerts: dict[UUID, ReviewAlert] = {}
    for assignment_id, reviewer_id, tenant_id in rows:
        await audit.append(
            tenant_id=tenant_id,
            actor_person_id=None,
            actor_type="system",
            action=ACTION,
            resource_type=RESOURCE,
            resource_id=assignment_id,
            payload={"reviewer_id": str(reviewer_id), "sender": "gold-review-push/1"},
            now=now,
        )
        alert = alerts.setdefault(reviewer_id, ReviewAlert(reviewer_id=reviewer_id))
        alert.assignments.append(assignment_id)
    devices: dict[UUID, list[str]] = defaultdict(list)
    for person_id, token in (
        await database.execute(
            select(LeadDevice.person_id, LeadDevice.token)
            .where(LeadDevice.person_id.in_(list(alerts)))
            .order_by(LeadDevice.last_seen_at.desc())
        )
    ).tuples():
        # One phone registered in two workspaces is still one phone.
        if token not in devices[person_id]:
            devices[person_id].append(token)
    for reviewer_id, alert in alerts.items():
        alert.tokens = devices.get(reviewer_id, [])
        alert.waiting = int((await badge(database, None, reviewer_id, now))["waiting"])
    return [alert for alert in alerts.values() if alert.tokens]


async def tick(
    sessions: async_sessionmaker[AsyncSession],
    fcm: Fcm,
    client: httpx.AsyncClient,
    *,
    now: datetime | None = None,
) -> int:
    """One pass: collect and record under a lock, commit, then send."""
    now = now or datetime.now(UTC)
    async with sessions() as database, database.begin():
        if not await database.scalar(
            text("SELECT pg_try_advisory_xact_lock(:a, :b)"), {"a": _LOCK[0], "b": _LOCK[1]}
        ):
            return 0
        alerts = await collect(database, now)
    sent = 0
    gone: list[str] = []
    for alert in alerts:
        data = alert.data()
        for token in alert.tokens:
            outcome = await fcm.send(client, token, data)
            sent += outcome == "sent"
            if outcome == "gone":
                gone.append(token)
    if gone:
        async with sessions() as database, database.begin():
            await database.execute(
                delete(LeadDevice).where(
                    LeadDevice.token_sha256.in_([token_digest(token) for token in gone])
                )
            )
    return sent
