"""Connected Google Sheets bring their new rows in by themselves (leads setup audit,
27 Oct 2026: a connected sheet changed only on "Sync", though "connected" reads as
automatic).

Every 10 minutes each active sheet source is read again and filed through the same
``Intake.file_sheet`` as "Sync": rows seen before read as "known", so nothing doubles.
Google is asked before anything is locked (it can be slow). The source is then locked with
SKIP LOCKED and checked again, so two API processes never file it twice. A sheet that
can't be read keeps the reason on its source ("problem", shown on its card) and is tried
again ten minutes later. Run from the API's minute loop (``push.run_hours_release``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select

SYNC_EVERY = 600  # seconds between reads of one sheet


def _due(config: Any, now: datetime) -> bool:
    synced = (config or {}).get("synced_at") if isinstance(config, dict) else None
    return not isinstance(synced, (int, float)) or now.timestamp() - synced >= SYNC_EVERY


async def sync_due(
    sessions: Any,
    now: datetime,
    *,
    fetch: Callable[[str], Awaitable[bytes]] | None = None,
) -> int:
    """Read every due sheet and file its new rows; returns how many leads it made."""
    from ac_platform.lead_desk.intake import Intake, sheet_csv_url
    from ac_platform.lead_desk.models import LeadSource
    from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer

    read = fetch or Intake._fetch_sheet
    async with sessions() as database:
        listed = (
            await database.execute(
                select(LeadSource.id, LeadSource.config).where(
                    LeadSource.kind == "sheet", LeadSource.active.is_(True)
                )
            )
        ).all()
    made = 0
    for source_id, config in listed:
        if not _due(config, now):
            continue
        data: bytes | None = None
        problem: str | None = None
        try:
            data = await read(sheet_csv_url(config))
        except DeskError as error:
            problem = str(error)
        except KeyError:
            problem = "This sheet's link is incomplete. Connect it again."
        async with sessions() as database, database.begin():
            source = await database.scalar(
                select(LeadSource)
                .where(LeadSource.id == source_id, LeadSource.active.is_(True))
                .with_for_update(skip_locked=True)
            )
            if source is None or not _due(source.config, now):
                continue
            if data is not None:
                desk = LeadDesk(
                    database,
                    Viewer(
                        person_id=source.created_by_person_id,
                        tenant_id=source.tenant_id,
                        role="system",
                        name=source.label,
                    ),
                    now=now,
                )
                try:
                    made += (await Intake(desk, app_url="").file_sheet(source, data)).created
                    continue
                except DeskError as error:
                    problem = str(error)
            source.config = {
                **(source.config or {}),
                "synced_at": now.timestamp(),
                "problem": problem,
            }
    return made
