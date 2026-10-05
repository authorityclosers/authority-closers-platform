"""Account-owned read state and environment-specific product note visibility."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
from ac_platform.kernel.authz import ActorContext
from ac_platform.product_updates.models import Notification, ProductUpdate, UpdateSeen
from ac_platform.tenancy.models import Membership, Organisation

FEATURE_REGISTRY: dict[str, Callable[[AsyncSession, ActorContext], Awaitable[bool]]] = {}


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
                        Membership.role.in_(("owner", "admin")),
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
                "title": "1 new update" if len(items) == 1 else f"{len(items)} new updates",
                "href": None,
                "urgent": False,
                "created_at": max(item.first_published_at or item.order_at for item in items),
                "read": all(item.seen for item in items),
            }
            for release_id, items in releases.items()
        ]
        unread = sum(not entry["read"] for entry in entries)
        unread += (
            await self.database.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.person_id == self.actor.person_id, Notification.read_at.is_(None)
                )
            )
            or 0
        )
        events = (
            await self.database.scalars(
                select(Notification)
                .where(Notification.person_id == self.actor.person_id)
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .limit(50)
            )
        ).all()
        entries.extend(
            {
                "id": str(event.id),
                "kind": event.kind,
                "title": event.title,
                "body": event.body,
                "href": event.href,
                "urgent": event.urgent,
                "created_at": utc(event.created_at),
                "read": event.read_at is not None,
            }
            for event in events
        )
        entries.sort(key=lambda entry: (entry["created_at"], entry["id"]), reverse=True)
        return {"notifications": entries[:50], "unread_count": unread}

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
