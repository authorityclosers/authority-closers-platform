"""Auto-reassign, on its own (owner reports #37-#42, 27 Oct 2026: "half things don't work").

Lead rules → Auto-reassign promises "new leads move after N minutes without a call", but
the move ran only when a manager pressed "Check now" (POST /sweep). This pass runs that
same sweep every minute, from the API's work-hours loop (``push.run_hours_release``), for
every workspace that has it switched on. The sweep's own rules hold: new leads only, no
call yet, not test data, nothing while work hours pause new leads.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def reassign_due(database: AsyncSession, now: datetime) -> int:
    """Move every switched-on workspace's new leads that nobody called in time."""
    from ac_platform.lead_desk.models import LeadDeskSettings
    from ac_platform.lead_desk.store import LeadDesk, Viewer

    moved = 0
    for row in (await database.scalars(select(LeadDeskSettings))).all():
        config = row.config if isinstance(row.config, dict) else {}
        if config.get("auto_reassign") is not True:
            continue
        desk = LeadDesk(
            database,
            Viewer(
                person_id=UUID(int=0), tenant_id=row.tenant_id, role="owner", name="Auto-reassign"
            ),
            now=now,
        )
        moved += await desk.sweep()
    return moved
