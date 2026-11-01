"""Account-owned read state and environment-specific product note visibility."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
from ac_platform.kernel.authz import ActorContext
from ac_platform.lead_desk import bell
from ac_platform.lead_desk.capture_reminder import BODY as REMINDER_BODY
from ac_platform.lead_desk.capture_reminder import KEY as CAPTURE_KEY
from ac_platform.lead_desk.capture_reminder import as_bell, reminder_day
from ac_platform.product_updates.models import Notification, ProductUpdate, UpdateSeen
from ac_platform.tenancy.models import Membership, Organisation
from ac_platform.tenancy.roles import roles_with

FEATURE_REGISTRY: dict[str, Callable[[AsyncSession, ActorContext], Awaitable[bool]]] = {}
# A capture reminder's day is an India day, as the seller's calls are counted.
INDIA = ZoneInfo("Asia/Kolkata")


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class VisibleUpdate:
    note: ProductUpdate
    first_published_at: datetime | None
    order_at: datetime
    seen: bool

    def response(self) -> dict[str, Any]:
        return {
            "key": self.note.note_key,
            "version": self.note.version,
            "release_id": self.note.release_id,
            "date": self.note.note_date,
            "title": self.note.title,
            "items": self.note.items,
            "major": self.note.major,
            "draft": self.note.status != "published",
            "seen": self.seen,
            "published_at": self.note.published_at,
        }


def release_title(items: Sequence[VisibleUpdate]) -> str:
    """A release's line in the bell: new only while some of it is unseen (phone personas
    ph1-27/ph1-53, 1 Nov 2026: "6 new updates" stayed after reading What's new)."""
    unseen = sum(not item.seen for item in items)
    count = unseen or len(items)
    words = f"{count} {'new ' if unseen else ''}update"
    return words if count == 1 else f"{words}s"


class ProductUpdatesReading:
    def __init__(
        self,
        database: AsyncSession,
        actor: ActorContext,
        *,
        environment: str,
        tester_policy: InternalTesterPolicy | None = None,
    ) -> None:
        self.database = database
        self.actor = actor
        self.environment = environment
        self.tester_policy = tester_policy

    async def visible(self) -> list[VisibleUpdate]:
        newest = (
            ProductUpdate.version
            if self.environment == "development"
            else case((ProductUpdate.status == "published", ProductUpdate.version))
        )
        lineages = (
            select(
                ProductUpdate.note_key,
                func.max(newest).label("version"),
                func.min(ProductUpdate.created_at).label("created_at"),
                func.min(ProductUpdate.published_at).label("published_at"),
            )
            .group_by(ProductUpdate.note_key)
            .subquery()
        )
        rows = (
            await self.database.execute(
                select(ProductUpdate, lineages.c.created_at, lineages.c.published_at).join(
                    lineages,
                    (ProductUpdate.note_key == lineages.c.note_key)
                    & (ProductUpdate.version == lineages.c.version),
                )
            )
        ).all()
        audiences = {"everyone": True}
        if any(note.audience == "org_admins" for note, _, _ in rows):
            audiences["org_admins"] = (
                await self.database.scalar(
                    select(Membership.person_id)
                    .join(Organisation, Organisation.tenant_id == Membership.tenant_id)
                    .where(
                        Membership.person_id == self.actor.person_id,
                        Membership.role.in_(roles_with("org.manage")),
                        Membership.status == "active",
                        Membership.ended_at.is_(None),
                    )
                    .limit(1)
                )
            ) is not None
        if any(note.audience == "testers" for note, _, _ in rows):
            audiences["testers"] = (
                self.tester_policy is not None
                and (
                    await self.tester_policy.for_actor(self.database, self.actor, "account_minutes")
                )
                is not None
            )
        features: dict[str, bool] = {}
        seen = set(
            (
                await self.database.scalars(
                    select(UpdateSeen.note_key).where(UpdateSeen.person_id == self.actor.person_id)
                )
            ).all()
        )
        visible = []
        for note, created_at, published_at in rows:
            if not audiences.get(note.audience, False):
                continue
            if note.feature_key is not None:
                if note.feature_key not in features:
                    resolver = FEATURE_REGISTRY.get(note.feature_key)
                    features[note.feature_key] = resolver is not None and await resolver(
                        self.database, self.actor
                    )
                if not features[note.feature_key]:
                    continue
            first_publish = None if published_at is None else utc(published_at)
            order_at = first_publish if note.status == "published" else utc(created_at)
            assert order_at is not None
            visible.append(VisibleUpdate(note, first_publish, order_at, note.note_key in seen))
        return sorted(visible, key=lambda item: (item.order_at, item.note.note_key), reverse=True)

    async def updates(self, since: datetime | None = None) -> dict[str, Any]:
        visible = await self.visible()
        return {
            "updates": [
                item.response()
                for item in visible
                if since is None
                or (item.first_published_at is not None and item.first_published_at > since)
            ][:100],
            "unseen_count": sum(not item.seen for item in visible),
        }

    async def _mark_seen(self, keys: Sequence[str]) -> None:
        if not keys:
            return
        insert = (
            sqlite_insert if self.database.get_bind().dialect.name == "sqlite" else postgres_insert
        )
        await self.database.execute(
            insert(UpdateSeen)
            .values([{"person_id": self.actor.person_id, "note_key": key} for key in set(keys)])
            .on_conflict_do_nothing(index_elements=["person_id", "note_key"])
        )

    async def mark_seen(self, keys: Sequence[str]) -> dict[str, int]:
        visible = await self.visible()
        requested = set(keys)
        await self._mark_seen(
            [item.note.note_key for item in visible if item.note.note_key in requested]
        )
        return {
            "unseen_count": sum(
                not item.seen and item.note.note_key not in requested for item in visible
            )
        }

    async def notifications(self) -> dict[str, Any]:
        releases: dict[str, list[VisibleUpdate]] = {}
        for item in await self.visible():
            releases.setdefault(item.note.release_id, []).append(item)
        entries = [
            {
                "id": f"updates:{release_id}",
                "kind": "updates",
                "count": len(items),
                "title": release_title(items),
                "href": None,
                "urgent": False,
                "created_at": max(item.first_published_at or item.order_at for item in items),
                "read": all(item.seen for item in items),
            }
            for release_id, items in releases.items()
        ]
        unread = sum(not entry["read"] for entry in entries)
        # A workspace's capture reminder shows only there: one per day, with the count
        # its own calls say (phone personas ph1-27, 1 Nov 2026: 2 and 4 for one day).
        # So does a "<name> is your lead now" line: its lead opens only there (lead_desk.bell;
        # QA robot 5a5fb451, 2 Nov 2026).
        here = and_(
            or_(
                Notification.dedupe_key.is_(None),
                ~Notification.dedupe_key.startswith(CAPTURE_KEY),
                Notification.tenant_id == self.actor.tenant_id,
            ),
            or_(Notification.kind != bell.KIND, Notification.tenant_id == self.actor.tenant_id),
        )
        unread += (
            await self.database.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.person_id == self.actor.person_id,
                    Notification.read_at.is_(None),
                    here,
                )
            )
            or 0
        )
        events = (
            await self.database.scalars(
                select(Notification)
                .where(Notification.person_id == self.actor.person_id, here)
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .limit(50)
            )
        ).all()
        counts = await self._capture_counts(events)
        # A lead line whose lead is gone or someone else's now is history: read, opening
        # nothing, never counted, so no banner rings for it (lead_desk.bell.stale).
        stale: set[UUID] = set()
        if self.actor.tenant_id is not None:
            found = await self.database.execute(
                select(Notification.id, Notification.href).where(
                    Notification.person_id == self.actor.person_id,
                    Notification.tenant_id == self.actor.tenant_id,
                    Notification.kind == bell.KIND,
                    Notification.read_at.is_(None),
                )
            )
            unread_leads = found.tuples().all()
            stale = await bell.stale(
                self.database,
                self.actor.tenant_id,
                self.actor.person_id,
                [
                    *unread_leads,
                    *((event.id, event.href) for event in events if event.kind == bell.KIND),
                ],
            )
            unread -= sum(1 for line_id, _ in unread_leads if line_id in stale)
        for event in events:
            # The capture reminder stays in the bell and names its day, older rows too,
            # with that day's count now: the calls it opens say the same (ph1-53).
            day = reminder_day(event.dedupe_key)
            title, urgent, href = as_bell(
                event.dedupe_key,
                event.title,
                event.urgent,
                event.href,
                counts.get(day) if day else None,
            )
            entries.append(
                {
                    "id": str(event.id),
                    "kind": event.kind,
                    "title": title,
                    "body": REMINDER_BODY if day else event.body,
                    "href": None if event.id in stale else href,
                    "urgent": urgent and event.id not in stale,
                    "created_at": utc(event.created_at),
                    "read": event.read_at is not None or event.id in stale,
                }
            )
        entries.sort(key=lambda entry: (entry["created_at"], entry["id"]), reverse=True)
        return {"notifications": entries[:50], "unread_count": unread}

    async def _capture_counts(self, events: Sequence[Notification]) -> dict[date, int]:
        """Each capture reminder's day in this workspace, counted now as the Calls line counts
        it (call_ai.missing_recordings.calls_today): the seller's own connected calls with no
        recording. Days older than the line reads (31) keep their stored words."""
        from ac_platform.call_ai.missing_recordings import calls_today  # the store is heavy

        tenant = self.actor.tenant_id
        if tenant is None:
            return {}
        now = datetime.now(UTC)
        today = now.astimezone(INDIA).date()
        days = {
            day
            for event in events
            if event.tenant_id == tenant
            and (day := reminder_day(event.dedupe_key)) is not None
            and timedelta(0) <= today - day <= timedelta(days=31)
        }
        counts: dict[date, int] = {}
        for day in sorted(days):
            found = await calls_today(
                self.database,
                tenant_id=tenant,
                person_id=self.actor.person_id,
                role="member",
                now=now,
                day=day,
            )
            counts[day] = found.missing.total
        return counts

    async def mark_read(self, ids: Sequence[str]) -> dict[str, int]:
        releases = {value.removeprefix("updates:") for value in ids if value.startswith("updates:")}
        await self._mark_seen(
            [
                item.note.note_key
                for item in await self.visible()
                if item.note.release_id in releases
            ]
        )
        events = []
        for value in ids:
            try:
                events.append(UUID(value))
            except ValueError:
                continue
        if events:
            await self.database.execute(
                update(Notification)
                .where(
                    Notification.person_id == self.actor.person_id,
                    Notification.id.in_(events),
                    Notification.read_at.is_(None),
                )
                .values(read_at=datetime.now(UTC))
            )
        return {"unread_count": (await self.notifications())["unread_count"]}

    async def mark_all_read(self) -> dict[str, int]:
        """Acknowledge the account's full visible feed, beyond the response limit."""
        await self._mark_seen(
            [item.note.note_key for item in await self.visible() if not item.seen]
        )
        await self.database.execute(
            update(Notification)
            .where(Notification.person_id == self.actor.person_id, Notification.read_at.is_(None))
            .values(read_at=datetime.now(UTC))
        )
        return {"unread_count": (await self.notifications())["unread_count"]}
