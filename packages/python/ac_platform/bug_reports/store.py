"""Bug reports: write one, list and read them for the team, and add to their history.

A report is written once with a 'new' status event. Everything the team does afterwards
(status, severity, area, notes, the work-board card) is another event; nothing is updated
or deleted. A report's state now is the newest event of each kind (its area falls back to
the one worked out when it arrived). Stores never commit: the request's transaction does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, func, literal, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.bug_reports.models import (
    AREAS,
    SEVERITIES,
    STATUSES,
    BugReport,
    BugReportEvent,
)
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Tenant

PAGE = 50
BOARD_CARD = r"^[A-Z]{2,8}-[0-9]{1,7}$"


class BugReportNotFound(LookupError):
    pass


class BugReportRefused(ValueError):
    """A change the history cannot take; the message is safe to show."""


@dataclass(frozen=True, slots=True)
class NewReport:
    person_id: UUID
    tenant_id: UUID | None
    command_id: UUID
    words: str
    blocks_work: bool
    area: str
    route: str
    context: dict[str, Any]
    client_errors: list[dict[str, Any]]
    user_agent: str


def _latest(kind: str, column: Any) -> Any:
    """The newest value of one kind of event, per report."""
    return (
        select(BugReportEvent.bug_id.label("bug_id"), column.label("value"))
        .where(BugReportEvent.kind == kind)
        .distinct(BugReportEvent.bug_id)
        .order_by(BugReportEvent.bug_id, BugReportEvent.created_at.desc(), BugReportEvent.id)
        .subquery()
    )


class BugReportStore:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    # ---------- writing ----------

    async def find_command(self, person_id: UUID, command_id: UUID) -> BugReport | None:
        return await self.database.scalar(
            select(BugReport).where(
                BugReport.person_id == person_id, BugReport.command_id == command_id
            )
        )

    async def create(
        self,
        report: NewReport,
        *,
        bug_id: UUID,
        now: datetime,
        screenshot: dict[str, Any] | None = None,
    ) -> BugReport:
        # One number at a time: reports are few, so a transaction lock is enough.
        await self.database.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('bug_reports.number'))")
        )
        number = int(await self.database.scalar(select(func.max(BugReport.number))) or 0) + 1
        row = BugReport(
            id=bug_id,
            number=number,
            tenant_id=report.tenant_id,
            person_id=report.person_id,
            command_id=report.command_id,
            words=report.words,
            blocks_work=report.blocks_work,
            area=report.area,
            route=report.route,
            context=report.context,
            client_errors=report.client_errors,
            user_agent=report.user_agent,
            created_at=now,
            **(screenshot or {}),
        )
        self.database.add(row)
        self.database.add(
            BugReportEvent(
                id=uuid4(),
                bug_id=bug_id,
                kind="status",
                status="new",
                actor="reporter",
                actor_person_id=report.person_id,
                created_at=now,
            )
        )
        await self.database.flush()
        return row

    async def change(
        self,
        bug_id: UUID,
        *,
        actor_person_id: UUID,
        now: datetime,
        status: str | None = None,
        severity: str | None = None,
        area: str | None = None,
        note: str | None = None,
    ) -> list[str]:
        """Add one event per field given; returns the kinds added (none when nothing moved)."""
        current = await self.state(bug_id)
        if status is not None and status not in STATUSES:
            raise BugReportRefused("Choose a status from the list.")
        if severity is not None and severity not in SEVERITIES:
            raise BugReportRefused("Choose a severity from the list.")
        if area is not None and area not in AREAS:
            raise BugReportRefused("Choose an area from the list.")
        note = " ".join(note.split())[:2000] if note else None
        if status == "closed" and status != current["status"] and not note:
            raise BugReportRefused("Say why it is closed (a duplicate, or not a bug).")
        events: list[BugReportEvent] = []

        def add(kind: str, **values: Any) -> None:
            # One microsecond apart, so the history reads in the order they were made.
            events.append(
                BugReportEvent(
                    id=uuid4(),
                    bug_id=bug_id,
                    kind=kind,
                    actor="staff",
                    actor_person_id=actor_person_id,
                    created_at=now + timedelta(microseconds=len(events)),
                    **values,
                )
            )

        if status is not None and status != current["status"]:
            add("status", status=status)
        if severity is not None and severity != current["severity"]:
            add("severity", severity=severity)
        if area is not None and area != current["area"]:
            add("area", area=area)
        if note:
            add("note", note=note)
        self.database.add_all(events)
        await self.database.flush()
        return [event.kind for event in events]

    async def record_card(self, bug_id: UUID, card: str, *, now: datetime) -> bool:
        """The work-board card this report raised; False when it already has one."""
        if not re.fullmatch(BOARD_CARD, card):
            raise BugReportRefused("A board card looks like AUT-1234.")
        await self.state(bug_id)
        existing = await self.database.scalar(
            select(BugReportEvent.board_card).where(
                BugReportEvent.bug_id == bug_id, BugReportEvent.kind == "board"
            )
        )
        if existing is not None:
            return False
        try:
            async with self.database.begin_nested():
                self.database.add(
                    BugReportEvent(
                        id=uuid4(),
                        bug_id=bug_id,
                        kind="board",
                        board_card=card,
                        actor="board",
                        actor_person_id=None,
                        created_at=now,
                    )
                )
        except IntegrityError:
            return False
        return True

    # ---------- reading ----------

    def _stated(self) -> Select[Any]:
        status = _latest("status", BugReportEvent.status)
        severity = _latest("severity", BugReportEvent.severity)
        area = _latest("area", BugReportEvent.area)
        board = _latest("board", BugReportEvent.board_card)
        return (
            select(
                BugReport,
                func.coalesce(status.c.value, literal("new")).label("status"),
                severity.c.value.label("severity"),
                func.coalesce(area.c.value, BugReport.area).label("current_area"),
                board.c.value.label("board_card"),
                Tenant.name.label("organisation"),
                Person.display_name.label("person_name"),
                Person.email.label("person_email"),
            )
            .outerjoin(status, status.c.bug_id == BugReport.id)
            .outerjoin(severity, severity.c.bug_id == BugReport.id)
            .outerjoin(area, area.c.bug_id == BugReport.id)
            .outerjoin(board, board.c.bug_id == BugReport.id)
            .outerjoin(Tenant, Tenant.id == BugReport.tenant_id)
            .outerjoin(Person, Person.id == BugReport.person_id)
        )

    @staticmethod
    def _summary(row: Any) -> dict[str, Any]:
        report: BugReport = row[0]
        return {
            "bug_id": str(report.id),
            "number": report.number,
            "created_at": report.created_at.isoformat(),
            "words": report.words,
            "blocks_work": report.blocks_work,
            "status": row.status,
            "severity": row.severity,
            "area": row.current_area,
            "route": report.route,
            "board_card": row.board_card,
            "organisation": (
                {"id": str(report.tenant_id), "name": row.organisation}
                if report.tenant_id is not None
                else None
            ),
            "person": {
                "id": str(report.person_id),
                "name": row.person_name,
                "email": row.person_email,
            },
            "has_screenshot": report.screenshot_key is not None,
            "app": (report.context or {}).get("app", {}),
            "device": (report.context or {}).get("device", {}),
            "error_count": len(report.client_errors or []),
        }

    async def page(
        self,
        *,
        status: str | None = None,
        severity: str | None = None,
        area: str | None = None,
        organisation: UUID | None = None,
        offset: int = 0,
        limit: int = PAGE,
    ) -> dict[str, Any]:
        stated = self._stated().subquery()
        filters = []
        if severity is not None:
            filters.append(
                stated.c.severity.is_(None) if severity == "none" else stated.c.severity == severity
            )
        if area is not None:
            filters.append(stated.c.current_area == area)
        if organisation is not None:
            filters.append(stated.c.tenant_id == organisation)
        # Counts per status under the other filters, for the status tabs.
        counted = await self.database.execute(
            select(stated.c.status, func.count()).where(*filters).group_by(stated.c.status)
        )
        counts = {name: 0 for name in STATUSES}
        counts.update({name: int(total) for name, total in counted.all()})
        if status == "open":
            filters.append(stated.c.status.in_(("new", "triaged", "in_progress")))
        elif status is not None:
            filters.append(stated.c.status == status)
        ids = (
            await self.database.scalars(
                select(stated.c.id)
                .where(*filters)
                .order_by(stated.c.created_at.desc(), stated.c.number.desc())
                .offset(offset)
                .limit(limit + 1)
            )
        ).all()
        more = len(ids) > limit
        ids = list(ids[:limit])
        rows = (
            (
                await self.database.execute(
                    self._stated()
                    .where(BugReport.id.in_(ids))
                    .order_by(BugReport.created_at.desc(), BugReport.number.desc())
                )
            ).all()
            if ids
            else []
        )
        organisations = await self.database.execute(
            select(Tenant.id, Tenant.name, func.count(BugReport.id))
            .join(BugReport, BugReport.tenant_id == Tenant.id)
            .group_by(Tenant.id, Tenant.name)
            .order_by(func.count(BugReport.id).desc(), Tenant.name)
        )
        return {
            "items": [self._summary(row) for row in rows],
            "counts": counts,
            "next_offset": offset + limit if more else None,
            "organisations": [
                {"id": str(tenant_id), "name": name, "count": int(total)}
                for tenant_id, name, total in organisations.all()
            ],
        }

    async def state(self, bug_id: UUID) -> dict[str, Any]:
        row = (await self.database.execute(self._stated().where(BugReport.id == bug_id))).first()
        if row is None:
            raise BugReportNotFound(str(bug_id))
        return self._summary(row)

    async def detail(self, bug_id: UUID) -> dict[str, Any]:
        row = (await self.database.execute(self._stated().where(BugReport.id == bug_id))).first()
        if row is None:
            raise BugReportNotFound(str(bug_id))
        report: BugReport = row[0]
        actors = await self.database.execute(
            select(
                BugReportEvent,
                Person.display_name,
                Person.email,
            )
            .outerjoin(Person, Person.id == BugReportEvent.actor_person_id)
            .where(BugReportEvent.bug_id == bug_id)
            .order_by(BugReportEvent.created_at, BugReportEvent.id)
        )
        history = [
            {
                "event_id": str(event.id),
                "kind": event.kind,
                "status": event.status,
                "severity": event.severity,
                "area": event.area,
                "note": event.note,
                "board_card": event.board_card,
                "actor": event.actor,
                "actor_name": name if event.actor != "board" else None,
                "actor_email": email if event.actor != "board" else None,
                "created_at": event.created_at.isoformat(),
            }
            for event, name, email in actors.all()
        ]
        return {
            **self._summary(row),
            "context": report.context,
            "client_errors": report.client_errors,
            "user_agent": report.user_agent,
            "screenshot": (
                {
                    "content_type": report.screenshot_type,
                    "bytes": report.screenshot_bytes,
                    "source": report.screenshot_source,
                }
                if report.screenshot_key is not None
                else None
            ),
            "history": history,
        }

    async def screenshot(self, bug_id: UUID) -> tuple[str, str, str]:
        """The picture's key, digest and type; BugReportNotFound when there is none."""
        row = (
            await self.database.execute(
                select(
                    BugReport.screenshot_key,
                    BugReport.screenshot_sha256,
                    BugReport.screenshot_type,
                ).where(BugReport.id == bug_id)
            )
        ).first()
        if row is None or row[0] is None:
            raise BugReportNotFound(str(bug_id))
        return row[0], row[1], row[2]

    async def without_card(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Reports that have not raised a work-board card yet, oldest first."""
        carded = select(BugReportEvent.bug_id).where(BugReportEvent.kind == "board")
        rows = (
            await self.database.execute(
                self._stated()
                .where(BugReport.id.not_in(carded))
                .order_by(BugReport.created_at, BugReport.number)
                .limit(limit)
            )
        ).all()
        out = []
        for row in rows:
            report: BugReport = row[0]
            summary = self._summary(row)
            out.append(
                {
                    "bug_id": summary["bug_id"],
                    "number": summary["number"],
                    "created_at": summary["created_at"],
                    "words": report.words[:1500],
                    "blocks_work": report.blocks_work,
                    "status": summary["status"],
                    "area": summary["area"],
                    "route": report.route,
                    "app": summary["app"],
                    "device": summary["device"],
                    "has_screenshot": summary["has_screenshot"],
                    "errors": (report.client_errors or [])[-5:],
                }
            )
        return out
