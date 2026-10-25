"""The duplicate scan: one organisation's leads through the duplicate engine (``dupes``), its
pairs kept in ``lead_desk_duplicate_pairs`` for the review queue (design:
docs/product/lead-desk/duplicates.md).

- One organisation at a time; never two organisations' leads together.
- Test data, Meta's testing-tool leads and leads merged into another are left out.
- A pair a person said is "not the same" never comes back.
- The pairs are derived data: each scan writes the pairs it found and removes the ones it no
  longer finds.
It reads leads and writes only its own table: nothing reaches a lead, a seller or an ad
platform.

The API runs it every six hours for every organisation with leads, one at a time under an
advisory lock, and an owner or manager can ask for it ("Look for duplicates").
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import delete, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.lead_desk import dupes
from ac_platform.lead_desk.capture import first_email, first_phone
from ac_platform.lead_desk.models import Lead, LeadDuplicateDecision, LeadDuplicatePair

log = logging.getLogger(__name__)

EVERY: Final = 6 * 60 * 60
_LOCK: Final = 1802_1264  # one scan per organisation across API processes
META_TEST_LEAD: Final = "<test lead:%"
# Payload keys that hold another phone or email of the same lead ("Alternate Contact No").
_PHONE_KEY = re.compile(r"phone|mobile|contact[ _]?no|whatsapp|alternate", re.IGNORECASE)
_EMAIL_KEY = re.compile(r"e_?mail", re.IGNORECASE)


def _more(payload: Mapping[str, Any] | None, pattern: re.Pattern[str], read: Any) -> list[str]:
    found: list[str] = []
    for key, value in (payload or {}).items():
        if isinstance(value, str) and pattern.search(str(key)):
            item = read(value)
            if item:
                found.append(item)
    return found


async def cards(db: AsyncSession, tenant_id: UUID) -> list[dupes.Card]:
    """One organisation's leads as the engine reads them."""
    rows = (
        await db.execute(
            select(
                Lead.id,
                Lead.name,
                Lead.phone,
                Lead.email,
                Lead.company,
                Lead.city,
                Lead.source,
                Lead.source_ref,
                Lead.source_label,
                Lead.created_at,
                Lead.payload,
            ).where(
                Lead.tenant_id == tenant_id,
                Lead.test_data.is_(False),
                Lead.merged_into_id.is_(None),
                Lead.name.not_like(META_TEST_LEAD),
            )
        )
    ).all()
    found: list[dupes.Card] = []
    for row in rows:
        phones = dict.fromkeys(
            [*([row.phone] if row.phone else []), *_more(row.payload, _PHONE_KEY, first_phone)]
        )
        emails = dict.fromkeys(
            [*([row.email] if row.email else []), *_more(row.payload, _EMAIL_KEY, first_email)]
        )
        found.append(
            dupes.Card(
                lead_id=row.id,
                tenant_id=tenant_id,
                name=row.name,
                phones=tuple(phones),
                emails=tuple(emails),
                company=row.company,
                city=row.city,
                source_ref=f"{row.source}:{row.source_ref}" if row.source_ref else None,
                form=row.source_label,
                received_at=row.created_at,
            )
        )
    return found


async def scan(db: AsyncSession, tenant_id: UUID, now: datetime) -> dict[str, Any]:
    """Find one organisation's pairs and keep them; the caller commits."""
    found = dupes.find(await cards(db, tenant_id))
    refused = set(
        (
            await db.execute(
                select(
                    LeadDuplicateDecision.first_lead_id, LeadDuplicateDecision.second_lead_id
                ).where(
                    LeadDuplicateDecision.tenant_id == tenant_id,
                    LeadDuplicateDecision.decision == "not_same",
                )
            )
        ).tuples()
    )
    kept = [pair for pair in found if (pair.first, pair.second) not in refused]
    wanted = {(pair.first, pair.second) for pair in kept}
    stale = [
        key
        for key in (
            await db.execute(
                select(LeadDuplicatePair.first_lead_id, LeadDuplicatePair.second_lead_id).where(
                    LeadDuplicatePair.tenant_id == tenant_id
                )
            )
        ).tuples()
        if key not in wanted
    ]
    if stale:
        await db.execute(
            delete(LeadDuplicatePair).where(
                LeadDuplicatePair.tenant_id == tenant_id,
                tuple_(LeadDuplicatePair.first_lead_id, LeadDuplicatePair.second_lead_id).in_(
                    stale
                ),
            )
        )
    for pair in kept:
        fields = {
            "score": pair.score,
            "band": pair.band,
            "reasons": list(pair.reasons),
            "against": list(pair.against),
            "computed_at": now,
        }
        await db.execute(
            insert(LeadDuplicatePair)
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                first_lead_id=pair.first,
                second_lead_id=pair.second,
                **fields,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "first_lead_id", "second_lead_id"], set_=fields
            )
        )
    return {
        "pairs": len(kept),
        "by_band": dict(Counter(pair.band for pair in kept)),
        "removed": len(stale),
        "not_same_kept_out": len(found) - len(kept),
    }


async def run_scans(
    sessions: async_sessionmaker[AsyncSession], stop: asyncio.Event, *, first_delay: int = 300
) -> None:
    """Every six hours, every organisation with leads, one at a time."""
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=first_delay)
    while not stop.is_set():
        try:
            async with sessions() as db:
                tenants = list((await db.scalars(select(Lead.tenant_id).distinct())).all())
            for tenant_id in tenants:
                if stop.is_set():
                    break
                async with sessions() as db, db.begin():
                    locked = await db.scalar(
                        text("SELECT pg_try_advisory_xact_lock(:a, hashtext(:t))"),
                        {"a": _LOCK, "t": str(tenant_id)},
                    )
                    if locked:
                        await scan(db, tenant_id, datetime.now(UTC))
        except Exception:  # noqa: BLE001 - the loop must survive a bad pass
            log.warning("lead desk duplicate scan failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=EVERY)
