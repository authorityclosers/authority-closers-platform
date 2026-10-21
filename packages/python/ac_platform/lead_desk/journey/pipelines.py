"""An organisation's pipelines (owner, 22 Oct 2026: "A for partner leads plus B for
enquiries as two pipelines").

A pipeline is its own list of lead stages (``lead_desk_journey_versions`` by
``pipeline_key``) and takes the new leads from the lead sources picked for it. An
organisation that never made a second one has a single pipeline, ``main``, with no row;
making the second writes ``main``'s row too. ``main`` takes every new lead no other
pipeline takes, so a lead always lands somewhere.

A lead keeps the desk's stage (its kind: new, couldn't reach, follow-up, interested, won,
lost), the same in every pipeline, so To call, Late and Start calling work across them;
its step is one of its own pipeline's stages.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk.journey.model import MAIN_PIPELINE, JourneyError
from ac_platform.lead_desk.journey.templates import slug
from ac_platform.lead_desk.models import Lead, LeadPipeline

MAIN: Final[str] = MAIN_PIPELINE
MAIN_NAME: Final[str] = "Leads"
MAX_PIPELINES: Final[int] = 8
MAX_NAME: Final[int] = 40
# Where a new lead came from (``Lead.source``), as a pipeline picks them, in the
# words the page shows.
SOURCES: Final[dict[str, str]] = {
    "meta": "Facebook and Instagram lead ads",
    "webhook": "Website forms and other apps",
    "sheet": "Google Sheets",
    "csv": "File imports",
    "manual": "Added by hand",
    "referral": "Referrals",
}


@dataclass(frozen=True, slots=True)
class Pipeline:
    key: str
    name: str
    position: int
    sources: tuple[str, ...]

    @property
    def main(self) -> bool:
        return self.key == MAIN


def _view(row: LeadPipeline) -> Pipeline:
    sources = row.sources if isinstance(row.sources, list) else []
    return Pipeline(
        row.key, row.name, row.position, tuple(item for item in sources if item in SOURCES)
    )


async def _rows(db: AsyncSession, tenant_id: UUID, *, lock: bool = False) -> list[LeadPipeline]:
    query = (
        select(LeadPipeline)
        .where(LeadPipeline.tenant_id == tenant_id)
        .order_by(LeadPipeline.position, LeadPipeline.created_at)
    )
    if lock:
        query = query.with_for_update()
    return list((await db.scalars(query)).all())


async def listed(db: AsyncSession, tenant_id: UUID) -> tuple[Pipeline, ...]:
    """The organisation's pipelines in its order; ``main`` alone when it never made one."""
    found = [_view(row) for row in await _rows(db, tenant_id)]
    if not any(item.main for item in found):
        found.insert(0, Pipeline(MAIN, MAIN_NAME, 0, ()))
    return tuple(found)


def route(pipelines: Sequence[Pipeline], source: str) -> str:
    """Where a new lead from this source goes: the first other pipeline that picked the
    source, else ``main``."""
    for item in pipelines:
        if not item.main and source in item.sources:
            return item.key
    return MAIN


def find(pipelines: Iterable[Pipeline], key: str) -> Pipeline:
    for item in pipelines:
        if item.key == key:
            return item
    raise JourneyError("That pipeline isn't there any more. Reload the page.")


async def lead_totals(db: AsyncSession, tenant_id: UUID) -> dict[str, int]:
    """How many leads each pipeline holds."""
    key = func.coalesce(Lead.pipeline_key, MAIN)
    rows = await db.execute(
        select(key, func.count()).where(Lead.tenant_id == tenant_id).group_by(key)
    )
    return {str(key): int(count) for key, count in rows.tuples()}


def clean_name(value: Any) -> str:
    name = " ".join(value.split()) if isinstance(value, str) else ""
    if not name:
        raise JourneyError("Give the pipeline a name.")
    if len(name) > MAX_NAME:
        raise JourneyError(f"Keep the name to {MAX_NAME} letters or fewer.")
    return name


def clean_sources(values: Iterable[Any]) -> tuple[str, ...]:
    picked: list[str] = []
    for value in values:
        if value not in SOURCES:
            raise JourneyError("Pick the lead sources from the list.")
        if value not in picked:
            picked.append(str(value))
    return tuple(picked)


def _taken_from_others(rows: Iterable[LeadPipeline], key: str, picked: Sequence[str]) -> None:
    """A source feeds one pipeline: picking it for one takes it from the others."""
    for row in rows:
        if row.key != key and isinstance(row.sources, list):
            kept = [item for item in row.sources if item not in picked]
            if kept != row.sources:
                row.sources = kept


def _main_row(tenant_id: UUID, by: UUID | None, now: datetime) -> LeadPipeline:
    return LeadPipeline(
        tenant_id=tenant_id,
        key=MAIN,
        name=MAIN_NAME,
        position=0,
        sources=[],
        created_by_person_id=by,
        created_at=now,
        updated_at=now,
    )


async def create(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    name: Any,
    sources: Iterable[Any],
    by: UUID,
    now: datetime,
) -> Pipeline:
    """A new pipeline after the others. Its stages come from the caller (a kind of business)."""
    rows = await _rows(db, tenant_id, lock=True)
    if not any(row.key == MAIN for row in rows):
        main = _main_row(tenant_id, by, now)
        db.add(main)
        rows.insert(0, main)
    if len(rows) >= MAX_PIPELINES:
        raise JourneyError(f"Keep it to {MAX_PIPELINES} pipelines or fewer.")
    clean = clean_name(name)
    if any(row.name.casefold() == clean.casefold() for row in rows):
        raise JourneyError("Another pipeline has that name. Give this one its own.")
    picked = clean_sources(sources)
    taken = {row.key for row in rows}
    base = slug(clean)
    key, n = base, 2
    while key in taken:
        suffix = f"_{n}"
        key = f"{base[: 40 - len(suffix)]}{suffix}"
        n += 1
    _taken_from_others(rows, key, picked)
    row = LeadPipeline(
        tenant_id=tenant_id,
        key=key,
        name=clean,
        position=max(item.position for item in rows) + 1,
        sources=list(picked),
        created_by_person_id=by,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    return _view(row)


async def change(
    db: AsyncSession,
    tenant_id: UUID,
    key: str,
    *,
    name: Any = None,
    sources: Iterable[Any] | None = None,
    by: UUID,
    now: datetime,
) -> Pipeline:
    """Rename a pipeline, or pick the sources whose new leads come to it."""
    rows = await _rows(db, tenant_id, lock=True)
    if key == MAIN and not any(row.key == MAIN for row in rows):
        main = _main_row(tenant_id, by, now)
        db.add(main)
        rows.insert(0, main)
    row = next((item for item in rows if item.key == key), None)
    if row is None:
        raise JourneyError("That pipeline isn't there any more. Reload the page.")
    if name is not None:
        clean = clean_name(name)
        if any(item.key != key and item.name.casefold() == clean.casefold() for item in rows):
            raise JourneyError("Another pipeline has that name. Give this one its own.")
        row.name = clean
    if sources is not None:
        if key == MAIN:
            raise JourneyError(
                "Your first pipeline takes every lead the others don't. "
                "Pick sources on the other pipelines."
            )
        picked = clean_sources(sources)
        _taken_from_others(rows, key, picked)
        row.sources = list(picked)
    row.updated_at = now
    await db.flush()
    return _view(row)
