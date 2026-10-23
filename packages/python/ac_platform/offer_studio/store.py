"""Reads and saves of shared offers in the operations workspace.

A save names the version it was based on; if someone saved since, it is refused (409) and
nothing is written, so two people never overwrite each other. Rows are only inserted.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationError,
    ConversationNotFound,
)
from ac_platform.identity.models import Person
from ac_platform.offer_studio.models import AdminOfferVersion

MAX_BODY_BYTES = 256_000
MAX_OFFERS = 500


class OfferTooLarge(ConversationError):
    status = 413


def offer_name(body: dict[str, Any]) -> str:
    """The name a version is listed by: the chosen name, else the working name."""
    naming = body.get("naming")
    chosen = naming.get("chosen") if isinstance(naming, dict) else None
    for candidate in (chosen, body.get("name")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()[:200]
    return "Untitled offer"


def check_body(body: dict[str, Any]) -> None:
    size = len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
    if size > MAX_BODY_BYTES:
        raise OfferTooLarge(f"An offer can be at most {MAX_BODY_BYTES // 1000} KB.")


class OfferStudioStore:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    @staticmethod
    def _summary(row: AdminOfferVersion, author: str | None) -> dict[str, Any]:
        return {
            "offer_id": str(row.offer_id),
            "version": row.version,
            "name": row.name,
            "archived": row.archived,
            "author": author,
            "created_at": row.created_at.isoformat(),
        }

    async def _authors(self, ids: set[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        rows = await self.database.execute(
            select(Person.id, Person.display_name, Person.email).where(Person.id.in_(ids))
        )
        return {pid: (name or email or "") for pid, name, email in rows.all()}

    async def latest(self, tenant_id: UUID) -> dict[str, Any]:
        """The newest version of every offer that isn't archived, newest first."""
        newest = (
            select(
                AdminOfferVersion.offer_id,
                func.max(AdminOfferVersion.version).label("version"),
            )
            .where(AdminOfferVersion.tenant_id == tenant_id)
            .group_by(AdminOfferVersion.offer_id)
            .subquery()
        )
        query = (
            select(AdminOfferVersion)
            .join(
                newest,
                (AdminOfferVersion.offer_id == newest.c.offer_id)
                & (AdminOfferVersion.version == newest.c.version),
            )
            .where(
                AdminOfferVersion.tenant_id == tenant_id,
                AdminOfferVersion.archived.is_(False),
            )
            .order_by(AdminOfferVersion.created_at.desc())
            .limit(MAX_OFFERS)
        )
        rows = (await self.database.execute(query)).scalars().all()
        authors = await self._authors({row.author_person_id for row in rows})
        return {
            "offers": [
                {**self._summary(row, authors.get(row.author_person_id)), "body": row.body}
                for row in rows
            ]
        }

    async def history(self, tenant_id: UUID, offer_id: UUID) -> dict[str, Any]:
        """Every version of one offer, newest first, without bodies."""
        query = (
            select(AdminOfferVersion)
            .where(
                AdminOfferVersion.tenant_id == tenant_id,
                AdminOfferVersion.offer_id == offer_id,
            )
            .order_by(AdminOfferVersion.version.desc())
        )
        rows = (await self.database.execute(query)).scalars().all()
        if not rows:
            raise ConversationNotFound("No shared offer has this id.")
        authors = await self._authors({row.author_person_id for row in rows})
        return {"versions": [self._summary(row, authors.get(row.author_person_id)) for row in rows]}

    async def version(self, tenant_id: UUID, offer_id: UUID, version: int) -> dict[str, Any]:
        query = select(AdminOfferVersion).where(
            AdminOfferVersion.tenant_id == tenant_id,
            AdminOfferVersion.offer_id == offer_id,
            AdminOfferVersion.version == version,
        )
        row = (await self.database.execute(query)).scalar_one_or_none()
        if row is None:
            raise ConversationNotFound("No such version.")
        authors = await self._authors({row.author_person_id})
        return {**self._summary(row, authors.get(row.author_person_id)), "body": row.body}

    async def save(
        self,
        *,
        tenant_id: UUID,
        person_id: UUID,
        offer_id: UUID,
        base_version: int | None,
        body: dict[str, Any],
        archived: bool,
        now: datetime,
    ) -> dict[str, Any]:
        """A new version on top of ``base_version`` (None: a new offer)."""
        check_body(body)
        query = (
            select(AdminOfferVersion)
            .where(AdminOfferVersion.offer_id == offer_id)
            .order_by(AdminOfferVersion.version.desc())
            .limit(1)
        )
        current = (await self.database.execute(query)).scalar_one_or_none()
        if current is not None and current.tenant_id != tenant_id:
            raise ConversationNotFound("No shared offer has this id.")
        if archived and current is None:
            raise ConversationNotFound("No shared offer has this id.")
        if (current.version if current else None) != base_version:
            raise ConversationConflict(
                "Someone saved this offer since you opened it. Open the newest version first."
            )
        row = AdminOfferVersion(
            id=uuid4(),
            tenant_id=tenant_id,
            offer_id=offer_id,
            version=(current.version + 1) if current else 1,
            name=offer_name(body),
            body=body,
            archived=archived,
            author_person_id=person_id,
            created_at=now,
        )
        try:
            async with self.database.begin_nested():
                self.database.add(row)
                await self.database.flush()
        except IntegrityError:
            raise ConversationConflict(
                "Someone saved this offer at the same moment. Open the newest version first."
            ) from None
        authors = await self._authors({person_id})
        return self._summary(row, authors.get(person_id))
