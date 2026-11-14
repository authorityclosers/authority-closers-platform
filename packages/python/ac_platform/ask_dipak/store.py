"""Ask Dipak progress: read, change and count (Dipak's spec, 13 Nov 2026; migration 0153).

Rows are only ever added. A person's saved lessons and missions are the newest row per
question and per item; a change that would not change that adds nothing, so a repeated tap or
a retry is harmless. Missions marked done are counted from the same rows.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.ask_dipak.catalogue import LESSON_IDS, QUESTION_IDS
from ac_platform.ask_dipak.models import SalesXrayAskDipakEvent

Item = Literal["saved", "mission"]

#: Each item's on and off kinds.
_KINDS: dict[str, tuple[str, str]] = {
    "saved": ("saved", "unsaved"),
    "mission": ("mission_done", "mission_undone"),
}
_ITEM_OF = {kind: item for item, kinds in _KINDS.items() for kind in kinds}


class UnknownQuestion(LookupError):
    """The question is not one of Dipak's 150."""


class NoMission(ValueError):
    """The question has no lesson yet, so no Next-call mission to mark."""


@dataclass(frozen=True)
class Progress:
    """Where a person stands: saved lessons and missions marked done, oldest first."""

    saved: tuple[str, ...]
    missions: tuple[str, ...]

    def public(self) -> dict[str, object]:
        return {
            "saved": list(self.saved),
            "missions": list(self.missions),
            "missions_done": len(self.missions),
        }


def fold(rows: list[tuple[str, str]]) -> Progress:
    """The newest row per question and item, from (question_id, kind) rows, oldest first."""
    state: dict[tuple[str, str], str] = {}
    for question_id, kind in rows:
        key = (question_id, _ITEM_OF[kind])
        state.pop(key, None)
        state[key] = kind
    return Progress(
        saved=tuple(question for (question, _), kind in state.items() if kind == "saved"),
        missions=tuple(question for (question, _), kind in state.items() if kind == "mission_done"),
    )


async def _rows(db: AsyncSession, person_id: UUID) -> list[tuple[str, str]]:
    result = await db.execute(
        select(SalesXrayAskDipakEvent.question_id, SalesXrayAskDipakEvent.kind)
        .where(SalesXrayAskDipakEvent.person_id == person_id)
        .order_by(SalesXrayAskDipakEvent.created_at, SalesXrayAskDipakEvent.id)
    )
    return [(question_id, kind) for question_id, kind in result.all()]


async def after_latest(db: AsyncSession, model: Any, person_id: UUID, now: datetime) -> datetime:
    """``now``, or just after the person's newest row in this table when that is not
    earlier: one person's rows always sort in the order they were written."""
    latest = await db.scalar(select(func.max(model.created_at)).where(model.person_id == person_id))
    return now if latest is None or latest < now else latest + timedelta(microseconds=1)


async def progress_for(db: AsyncSession, person_id: UUID) -> Progress:
    return fold(await _rows(db, person_id))


async def set_item(
    db: AsyncSession,
    *,
    person_id: UUID,
    tenant_id: UUID | None,
    question_id: str,
    item: Item,
    on: bool,
    now: datetime,
) -> Progress:
    """Saves or clears a lesson, or marks or undoes its mission; returns where they stand."""
    if question_id not in QUESTION_IDS:
        raise UnknownQuestion(question_id)
    if item == "mission" and question_id not in LESSON_IDS:
        raise NoMission(question_id)
    current = await progress_for(db, person_id)
    present = question_id in (current.saved if item == "saved" else current.missions)
    if present == on:
        return current
    on_kind, off_kind = _KINDS[item]
    db.add(
        SalesXrayAskDipakEvent(
            id=uuid4(),
            person_id=person_id,
            tenant_id=tenant_id,
            question_id=question_id,
            kind=on_kind if on else off_kind,
            created_at=await after_latest(db, SalesXrayAskDipakEvent, person_id, now),
        )
    )
    await db.flush()
    if item == "mission" and not on:
        # An unticked mission is no longer one of the seller's active three.
        from ac_platform.ask_dipak.coaching import set_active

        await set_active(
            db,
            person_id=person_id,
            tenant_id=tenant_id,
            question_id=question_id,
            on=False,
            now=now,
        )
    return await progress_for(db, person_id)


async def missions_marked(db: AsyncSession, person_id: UUID) -> Counter[str]:
    """How many times the person has marked each lesson's mission done (for Growth)."""
    result = await db.execute(
        select(SalesXrayAskDipakEvent.question_id).where(
            SalesXrayAskDipakEvent.person_id == person_id,
            SalesXrayAskDipakEvent.kind == "mission_done",
        )
    )
    return Counter(result.scalars().all())


async def erase_ask_dipak_for_person(db: AsyncSession, *, person_id: UUID) -> int:
    """Remove a person's Ask Dipak progress in the canonical account-deletion transaction
    (their saved lessons and ticks here; coaching.erase_coaching_for_person the rest)."""
    result = await db.execute(
        delete(SalesXrayAskDipakEvent).where(SalesXrayAskDipakEvent.person_id == person_id)
    )
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = [
    "Item",
    "NoMission",
    "Progress",
    "UnknownQuestion",
    "erase_ask_dipak_for_person",
    "fold",
    "missions_marked",
    "progress_for",
    "set_item",
]
