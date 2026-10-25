"""Bug issues: reports that look like one problem, worked as one (owner, 25 Oct 2026: bug
alerts reach the team by themselves, reports are "combined, analysed and clubbed together",
fixed the same day or in the next update, then marked fixed "via bugs api cli" and the
reporter sees it in the app; v0.93).

- Every report gets a fingerprint: its screen (the route with ids taken out), and the
  newest error's kind and message when it carries one, else the report's own key words.
  Reports with one fingerprint form one issue. The app version is not part of it, so a
  report on a solved issue reopens it ("came back after the fix").
- An issue's history is append-only (``bug_issue_events``): its status (new, fixing,
  fixed in the next update, solved), notes, the commit that fixed it and the release that
  carried it, and who changed it (staff, an agent by name, or the release itself).
- A status change reaches each report on the issue as the report's own status event
  (actor "board": the automation), so Admin, the reporter's own list and the "Solved"
  corner card follow; when it is solved, each reporter also gets a notification in the
  app's bell, once per report.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.bug_reports.models import (
    ISSUE_STATUSES,
    BugIssue,
    BugIssueEvent,
    BugIssueReport,
    BugReport,
    BugReportEvent,
)

# What a report's own status becomes when its issue moves.
REPORT_STATUS = {"fixing": "in_progress", "fixed_next": "in_progress", "solved": "fixed"}
STATUS_WORDS = {
    "new": "New",
    "fixing": "Fixing",
    "fixed_next": "Fixed in the next update",
    "solved": "Solved",
}
_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|(?<![a-z])\d+(?![a-z])",
    re.I,
)
_WORD = re.compile(r"[a-z]{4,}")
_STOP = frozenset(
    [
        "this",
        "that",
        "with",
        "when",
        "then",
        "there",
        "here",
        "have",
        "from",
        "they",
        "them",
        "their",
        "what",
        "which",
        "would",
        "could",
        "should",
        "about",
        "into",
        "some",
        "more",
        "very",
        "also",
        "just",
        "like",
        "make",
        "made",
        "need",
        "needs",
        "needed",
        "want",
        "it's",
        "isn't",
        "doesn't",
        "does",
        "dont",
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "your",
        "our",
        "its",
        "was",
        "were",
        "been",
        "being",
        "will",
        "can't",
        "cant",
        "clicked",
        "click",
        "tapped",
        "tap",
        "open",
        "opens",
        "screen",
        "page",
        "please",
        "really",
        "still",
        "even",
        "only",
        "after",
        "before",
        "again",
    ]
)
SEP = "|"


class BugIssueRefused(ValueError):
    """A change an issue does not take (an unknown status, a bad commit)."""


class BugIssueNotFound(LookupError):
    """No such issue."""


def route_template(route: str) -> str:
    """The screen: the path without its query, fragment or ids."""
    path = (route or "/").split("?", 1)[0].split("#", 1)[0] or "/"
    return _ID.sub(":id", path.lower())[:200]


def error_signature(errors: object) -> str | None:
    """The newest error's kind, status and message with numbers taken out, if any."""
    if not isinstance(errors, list):
        return None
    for item in reversed(errors):
        if not isinstance(item, dict) or item.get("kind") not in ("error", "rejection", "http"):
            continue
        message = " ".join(str(item.get("message") or item.get("path") or "").split())
        message = re.sub(r"\d+", "#", _ID.sub("#", message.lower()))[:120]
        status = item.get("status") if isinstance(item.get("status"), int) else ""
        return f"{item['kind']}:{status}:{message}"[:200]
    return None


def key_words(words: str) -> str:
    """A report's key words, sorted, so the same complaint in other words order matches."""
    found = {word for word in _WORD.findall((words or "").lower()) if word not in _STOP}
    return " ".join(sorted(found)[:10])


def fingerprint(route: str, area: str, errors: object, words: str) -> tuple[str, str, str | None]:
    """(sha256 of the basis, screen, error signature)."""
    screen = route_template(route)
    signature = error_signature(errors)
    basis = SEP.join(
        (screen, signature) if signature else (screen, area or "other", key_words(words))
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest(), screen, signature


def _part(context: dict[str, Any], key: str) -> dict[str, Any]:
    value = context.get(key)
    return value if isinstance(value, dict) else {}


def _device(report: BugReport) -> tuple[str, str, str]:
    context = report.context if isinstance(report.context, dict) else {}
    device, app = _part(context, "device"), _part(context, "app")
    model = str(device.get("model") or device.get("browser") or "unknown")[:60]
    system = str(device.get("os") or "unknown")[:40]
    version = str(app.get("native_version") or app.get("release") or app.get("channel") or "")
    return model, system, version[:40] or "unknown"


class IssueStore:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def _lock(self) -> None:
        bind = self.database.get_bind()
        if getattr(getattr(bind, "dialect", None), "name", None) == "postgresql":
            await self.database.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('bug_issues.number'))")
            )

    async def status(self, issue_id: UUID) -> str:
        value = await self.database.scalar(
            select(BugIssueEvent.status)
            .where(BugIssueEvent.issue_id == issue_id, BugIssueEvent.kind == "status")
            .order_by(BugIssueEvent.created_at.desc(), BugIssueEvent.id.desc())
            .limit(1)
        )
        return value or "new"

    async def assign(self, report: BugReport, *, now: datetime) -> tuple[BugIssue, str]:
        """Joins the report to its issue; returns the issue and "new", "joined" or "reopened"."""
        linked = await self.database.scalar(
            select(BugIssueReport.issue_id).where(BugIssueReport.bug_id == report.id)
        )
        if linked is not None:
            issue = await self.database.get(BugIssue, linked)
            assert issue is not None
            return issue, "joined"
        key, screen, signature = fingerprint(
            report.route, report.area, report.client_errors, report.words
        )
        await self._lock()
        issue = await self.database.scalar(select(BugIssue).where(BugIssue.fingerprint == key))
        outcome = "joined"
        events: list[BugIssueEvent] = []
        if issue is None:
            number = int(await self.database.scalar(select(func.max(BugIssue.number))) or 0) + 1
            issue = BugIssue(
                id=uuid4(),
                number=number,
                fingerprint=key,
                route=screen,
                area=report.area,
                signature=signature,
                created_at=now,
            )
            self.database.add(issue)
            await self.database.flush()
            events.append(self._event(issue.id, now, kind="status", status="new", actor="system"))
            outcome = "new"
        elif await self.status(issue.id) == "solved":
            events.append(
                self._event(
                    issue.id, now, kind="reopened", note="Came back after the fix", actor="system"
                )
            )
            events.append(
                self._event(issue.id, now, kind="status", status="new", actor="system", order=1)
            )
            outcome = "reopened"
        self.database.add_all(events)
        self.database.add(BugIssueReport(bug_id=report.id, issue_id=issue.id, created_at=now))
        await self.database.flush()
        return issue, outcome

    async def link_unlinked(self, *, now: datetime, limit: int = 200) -> int:
        """Joins reports made before issues existed (or missed) to their issues, oldest first."""
        rows = (
            await self.database.scalars(
                select(BugReport)
                .where(~BugReport.id.in_(select(BugIssueReport.bug_id)))
                .order_by(BugReport.created_at)
                .limit(limit)
            )
        ).all()
        for report in rows:
            await self.assign(report, now=now)
        return len(rows)

    def _event(
        self,
        issue_id: UUID,
        now: datetime,
        *,
        kind: str,
        actor: str,
        order: int = 0,
        **values: Any,
    ) -> BugIssueEvent:
        return BugIssueEvent(
            id=uuid4(),
            issue_id=issue_id,
            kind=kind,
            actor=actor,
            created_at=now + timedelta(microseconds=order),
            **values,
        )

    async def _issue(self, ref: str | UUID) -> BugIssue:
        issue: BugIssue | None
        if isinstance(ref, UUID):
            issue = await self.database.get(BugIssue, ref)
        elif re.fullmatch(r"\d{1,9}", str(ref)):
            issue = await self.database.scalar(select(BugIssue).where(BugIssue.number == int(ref)))
        else:
            try:
                issue = await self.database.get(BugIssue, UUID(str(ref)))
            except ValueError:
                issue = None
        if issue is None:
            raise BugIssueNotFound("No such issue.")
        return issue

    async def _summaries(self, issues: list[BugIssue]) -> list[dict[str, Any]]:
        if not issues:
            return []
        ids = [issue.id for issue in issues]
        reports = (
            await self.database.execute(
                select(BugIssueReport.issue_id, BugReport)
                .join(BugReport, BugReport.id == BugIssueReport.bug_id)
                .where(BugIssueReport.issue_id.in_(ids))
                .order_by(BugReport.created_at)
            )
        ).all()
        events = (
            await self.database.scalars(
                select(BugIssueEvent)
                .where(BugIssueEvent.issue_id.in_(ids))
                .order_by(BugIssueEvent.created_at, BugIssueEvent.id)
            )
        ).all()
        by_issue: dict[UUID, list[BugReport]] = {issue_id: [] for issue_id in ids}
        for issue_id, report in reports:
            by_issue[issue_id].append(report)
        state: dict[UUID, dict[str, Any]] = {
            issue_id: {"status": "new", "came_back": False, "commit": None, "release": None}
            for issue_id in ids
        }
        for event in events:
            current = state[event.issue_id]
            if event.kind == "status":
                current["status"] = event.status
                current["status_at"] = event.created_at.isoformat()
                if event.commit_sha:
                    current["commit"] = event.commit_sha
                if event.release:
                    current["release"] = event.release
            elif event.kind == "reopened":
                current["came_back"] = True
        out = []
        for issue in issues:
            rows = by_issue[issue.id]
            devices = Counter(_device(report)[0] for report in rows)
            systems = Counter(_device(report)[1] for report in rows)
            versions = Counter(_device(report)[2] for report in rows)
            out.append(
                {
                    "id": str(issue.id),
                    "number": issue.number,
                    "screen": issue.route,
                    "area": issue.area,
                    "signature": issue.signature,
                    **state[issue.id],
                    "count": len(rows),
                    "first_seen": rows[0].created_at.isoformat() if rows else None,
                    "last_seen": rows[-1].created_at.isoformat() if rows else None,
                    "devices": dict(devices.most_common(5)),
                    "android": dict(systems.most_common(5)),
                    "app_versions": dict(versions.most_common(5)),
                    "orgs": len({report.tenant_id for report in rows if report.tenant_id}),
                    "reports": [
                        {"id": str(report.id), "number": report.number} for report in rows[-20:]
                    ],
                }
            )
        return out

    async def issues(
        self, *, which: str = "open", since: datetime | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Newest activity first. ``which``: new, open (not solved), solved or all;
        ``since``: only issues with a report made since then."""
        query = select(BugIssue)
        if since is not None:
            query = query.where(
                BugIssue.id.in_(
                    select(BugIssueReport.issue_id).where(BugIssueReport.created_at >= since)
                )
            )
        issues = (await self.database.scalars(query)).all()
        summaries = await self._summaries(list(issues))
        if which == "new":
            summaries = [item for item in summaries if item["status"] == "new"]
        elif which == "open":
            summaries = [item for item in summaries if item["status"] != "solved"]
        elif which == "solved":
            summaries = [item for item in summaries if item["status"] == "solved"]
        summaries.sort(key=lambda item: item["last_seen"] or "", reverse=True)
        return summaries[:limit]

    async def detail(self, ref: str | UUID) -> dict[str, Any]:
        issue = await self._issue(ref)
        summary = (await self._summaries([issue]))[0]
        events = (
            await self.database.scalars(
                select(BugIssueEvent)
                .where(BugIssueEvent.issue_id == issue.id)
                .order_by(BugIssueEvent.created_at, BugIssueEvent.id)
            )
        ).all()
        summary["history"] = [
            {
                "kind": event.kind,
                "status": event.status,
                "note": event.note,
                "commit": event.commit_sha,
                "release": event.release,
                "actor": event.actor,
                "actor_name": event.actor_name,
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ]
        return summary

    async def set_status(
        self,
        ref: str | UUID,
        *,
        status: str,
        now: datetime,
        actor: str,
        note: str | None = None,
        commit: str | None = None,
        release: str | None = None,
        app_update: bool = False,
        actor_person_id: UUID | None = None,
        actor_name: str | None = None,
    ) -> dict[str, Any]:
        """Moves an issue and every report on it; solved tells each reporter in the bell."""
        if status not in ISSUE_STATUSES:
            raise BugIssueRefused("Choose new, fixing, fixed_next or solved.")
        if commit is not None and not re.fullmatch(r"[0-9a-f]{7,40}", commit):
            raise BugIssueRefused("A commit is 7 to 40 hex characters.")
        issue = await self._issue(ref)
        note = " ".join(note.split())[:2000] if note else None
        events = [
            self._event(
                issue.id,
                now,
                kind="status",
                status=status,
                commit_sha=commit,
                release=release[:32] if release else None,
                app_update=app_update,
                actor=actor,
                actor_person_id=actor_person_id,
                actor_name=actor_name[:80] if actor_name else None,
            )
        ]
        if note:
            events.append(
                self._event(
                    issue.id,
                    now,
                    kind="note",
                    note=note,
                    actor=actor,
                    actor_person_id=actor_person_id,
                    actor_name=actor_name[:80] if actor_name else None,
                    order=1,
                )
            )
        self.database.add_all(events)
        reports = (
            await self.database.scalars(
                select(BugReport)
                .join(BugIssueReport, BugIssueReport.bug_id == BugReport.id)
                .where(BugIssueReport.issue_id == issue.id)
            )
        ).all()
        report_status = REPORT_STATUS.get(status)
        told = 0
        for report in reports:
            if report_status:
                self.database.add(
                    BugReportEvent(
                        id=uuid4(),
                        bug_id=report.id,
                        kind="status",
                        status=report_status,
                        actor="board",
                        created_at=now,
                    )
                )
            words = STATUS_WORDS[status] + (f": {note}" if note else "")
            self.database.add(
                BugReportEvent(
                    id=uuid4(),
                    bug_id=report.id,
                    kind="note",
                    note=f"Issue {issue.number}: {words}"[:2000],
                    actor="board",
                    created_at=now + timedelta(microseconds=1),
                )
            )
            if status == "solved":
                told += await self._tell(report, app_update=app_update, now=now)
        await self.database.flush()
        detail = await self.detail(issue.id)
        detail["reporters_told"] = told
        return detail

    async def _tell(self, report: BugReport, *, app_update: bool, now: datetime) -> int:
        """One bell notification per solved report, the first time only."""
        from ac_platform.product_updates.models import Notification

        key = f"bug-solved:{report.id}"
        seen = await self.database.scalar(
            select(Notification.id).where(
                Notification.person_id == report.person_id, Notification.dedupe_key == key
            )
        )
        if seen is not None:
            return 0
        first = " ".join((report.words or "").split())
        title = first if len(first) <= 70 else first[:69].rstrip() + "…"
        body = "Thanks for telling us; it's in the latest update."
        if app_update:
            body += " Update the app to get it."
        self.database.add(
            Notification(
                id=uuid4(),
                person_id=report.person_id,
                tenant_id=report.tenant_id,
                kind="bug_solved",
                dedupe_key=key,
                title=f"Fixed: {title}"[:200],
                body=body,
                href="/",
                urgent=False,
                created_at=now,
            )
        )
        return 1
