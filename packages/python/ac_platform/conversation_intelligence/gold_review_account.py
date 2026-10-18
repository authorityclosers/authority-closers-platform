"""Gold review from the Sales Xray app: a standing reviewer's own account session.

The phone review (owner, 19 Oct) reuses the 16 Oct gold service unchanged: the
same assignments, append-only rows, source/retention guards and erasure. Only
the admission differs. The Admin reviewer workspace admits a dedicated reviewer
session; here a signed-in account qualifies only while its verified person is a
standing gold reviewer, and only for that person's own gold assignments.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership

from .application import ConversationDenied, utc
from .gold_review_models import GoldAssignment, GoldReviewer, GoldRow
from .models import (
    ConversationRecording,
    ConversationReviewAssignment,
    ConversationReviewRevocation,
)
from .pointer_review_models import ConversationPointerReview
from .review_service import ConversationReviewService

LINES = 29
# Reviewers work in India; "today" is their day, not UTC's.
DAY_ZONE = ZoneInfo("Asia/Kolkata")
MAX_ROWS = 50_000
NOT_A_REVIEWER = "Review is open to designated gold reviewers."


def account_actor(actor: ActorContext) -> ActorContext:
    """Gold assignments span call tenants, so the reviewer acts outside a workspace."""
    return ActorContext(actor.person_id, actor.session_id, None)


async def standing_reviewer(database: Any, person_id: UUID) -> bool:
    return (
        await database.scalar(
            select(GoldReviewer.person_id).where(
                GoldReviewer.person_id == person_id, GoldReviewer.revoked_at.is_(None)
            )
        )
        is not None
    )


async def operations_owner(database: Any, operations_tenant_id: UUID, person_id: UUID) -> bool:
    """The AC operations workspace's owners and admins see everyone's figures."""
    return (
        await database.scalar(
            select(Membership.person_id).where(
                Membership.tenant_id == operations_tenant_id,
                Membership.person_id == person_id,
                Membership.role.in_(("owner", "admin")),
                Membership.status == "active",
            )
        )
        is not None
    )


class AccountGoldReviewService(ConversationReviewService):
    """The canonical review service with account-session admission for gold reviewers."""

    async def _reviewer(self, actor: ActorContext) -> datetime:
        now = utc(self.application.clock())
        if actor.tenant_id is not None:
            raise ConversationDenied(NOT_A_REVIEWER)
        await self._reviewer_person(actor.person_id)
        designation = await self.database.scalar(
            select(GoldReviewer)
            .where(GoldReviewer.person_id == actor.person_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if designation is None or designation.revoked_at is not None:
            raise ConversationDenied(NOT_A_REVIEWER)
        return now


async def _assignments(database: Any, person_id: UUID, now: datetime) -> list[dict[str, Any]]:
    """This reviewer's live gold assignments, newest first, with lines handled."""
    rows = (
        await database.execute(
            select(GoldAssignment, ConversationReviewAssignment, ConversationRecording)
            .join(
                ConversationReviewAssignment,
                ConversationReviewAssignment.id == GoldAssignment.assignment_id,
            )
            .join(ConversationRecording, ConversationRecording.id == GoldAssignment.recording_id)
            .where(
                GoldAssignment.reviewer_id == person_id,
                ConversationReviewAssignment.expires_at > now,
                ConversationRecording.deleted_at.is_(None),
                ~select(ConversationReviewRevocation.assignment_id)
                .where(ConversationReviewRevocation.assignment_id == GoldAssignment.assignment_id)
                .exists(),
            )
            .order_by(GoldAssignment.created_at.desc(), GoldAssignment.assignment_id)
            .limit(500)
        )
    ).all()
    ids = [gold.assignment_id for gold, _, _ in rows]
    handled: dict[UUID, int] = {}
    if ids:
        handled = {
            assignment_id: int(count)
            for assignment_id, count in (
                await database.execute(
                    select(GoldRow.assignment_id, func.count(func.distinct(GoldRow.target)))
                    .where(GoldRow.assignment_id.in_(ids), GoldRow.erased_at.is_(None))
                    .group_by(GoldRow.assignment_id)
                )
            ).all()
        }
    items = []
    for gold, assignment, recording in rows:
        done = min(handled.get(gold.assignment_id, 0), LINES)
        items.append(
            {
                "assignment_id": str(gold.assignment_id),
                "recording_id": str(gold.recording_id),
                "assigned_at": utc(gold.created_at).isoformat(),
                "recorded_at": utc(recording.created_at).isoformat(),
                "expires_at": utc(assignment.expires_at).isoformat(),
                "handled": done,
                "total": LINES,
                "state": "done" if done >= LINES else "in_progress" if done else "new",
            }
        )
    return items


async def badge(
    database: Any, operations_tenant_id: UUID | None, person_id: UUID, now: datetime
) -> dict[str, Any]:
    reviewer = await standing_reviewer(database, person_id)
    owner = operations_tenant_id is not None and await operations_owner(
        database, operations_tenant_id, person_id
    )
    if not reviewer:
        return {"reviewer": False, "metrics": owner, "waiting": 0, "newest_at": None}
    waiting = [
        item for item in await _assignments(database, person_id, now) if item["state"] != "done"
    ]
    return {
        "reviewer": True,
        "metrics": True,
        "waiting": len(waiting),
        "newest_at": max((item["assigned_at"] for item in waiting), default=None),
    }


async def queue(database: Any, person_id: UUID, now: datetime) -> dict[str, Any]:
    if not await standing_reviewer(database, person_id):
        raise ConversationDenied(NOT_A_REVIEWER)
    items = await _assignments(database, person_id, now)
    # Started calls first, then the newest; finished calls stay reachable at the end.
    ordered = [i for i in items if i["state"] == "in_progress"]
    ordered += sorted(
        (i for i in items if i["state"] == "new"), key=lambda i: i["assigned_at"], reverse=True
    )
    ordered += [i for i in items if i["state"] == "done"]
    return {
        "items": ordered[:200],
        "calls_left": sum(1 for i in items if i["state"] != "done"),
        "lines_left": sum(LINES - i["handled"] for i in items if i["state"] != "done"),
    }


def _heads(rows: list[GoldRow]) -> list[GoldRow]:
    superseded = {row.supersedes_id for row in rows if row.supersedes_id}
    return [row for row in rows if row.id not in superseded and row.payload is not None]


def _day(moment: datetime) -> date:
    return utc(moment).astimezone(DAY_ZONE).date()


def _rate(agree: int, partly: int, disagree: int) -> float | None:
    total = agree + partly + disagree
    return None if total == 0 else round((agree + 0.5 * partly) / total, 3)


def _median(values: list[int]) -> float | None:
    return round(statistics.median(values), 1) if values else None


async def _labels(database: Any) -> dict[str, str]:
    """Pointer names from the newest saved AI review; the ids are stable across calls."""
    payload = await database.scalar(
        select(ConversationPointerReview.payload)
        .where(
            ConversationPointerReview.version == "pointer-review/1",
            ConversationPointerReview.erased_at.is_(None),
        )
        .order_by(ConversationPointerReview.created_at.desc())
        .limit(1)
    )
    labels = {"final_call_outcome": "Final Call Outcome", "coaching": "Coaching"}
    pointers = payload.get("pointers") if isinstance(payload, dict) else None
    for p in pointers if isinstance(pointers, list) else []:
        if isinstance(p, dict) and isinstance(p.get("id"), str):
            labels[p["id"]] = f"{p.get('number')}. {p.get('label')}"
    return labels


async def metrics(
    database: Any, operations_tenant_id: UUID | None, person_id: UUID, now: datetime
) -> dict[str, Any]:
    """Counts only: no call content, quotes or opinions leave this read."""
    reviewer = await standing_reviewer(database, person_id)
    owner = operations_tenant_id is not None and await operations_owner(
        database, operations_tenant_id, person_id
    )
    if not reviewer and not owner:
        raise ConversationDenied(NOT_A_REVIEWER)
    rows = list(
        (
            await database.scalars(
                select(GoldRow)
                .where(GoldRow.erased_at.is_(None))
                .order_by(GoldRow.created_at, GoldRow.id)
                .limit(MAX_ROWS)
            )
        ).all()
    )
    heads = _heads(rows)
    labels = await _labels(database)
    today = _day(now)

    def judged(row: GoldRow) -> bool:
        return not (row.payload or {}).get("skip")

    def summary(selected: list[GoldRow]) -> dict[str, Any]:
        verdicts = Counter((r.payload or {}).get("verdict") for r in selected if judged(r))
        seconds = [
            s
            for r in selected
            if type(s := (r.payload or {}).get("seconds")) is int and 0 < s <= 900
        ]
        calls: dict[UUID, set[str]] = defaultdict(set)
        for r in selected:
            calls[r.assignment_id].add(r.target)
        return {
            "labels": sum(1 for r in selected if judged(r)),
            "skipped": sum(1 for r in selected if not judged(r)),
            "today": sum(1 for r in selected if _day(r.created_at) == today),
            "calls_done": sum(1 for targets in calls.values() if len(targets) >= LINES),
            "calls_started": len(calls),
            "median_seconds": _median(seconds),
            "agreement": _rate(verdicts["agree"], verdicts["partly"], verdicts["disagree"]),
            "verdicts": {k: verdicts[k] for k in ("agree", "partly", "disagree")},
        }

    mine = [r for r in heads if r.reviewer_id == person_id]
    me: dict[str, Any] | None = None
    if reviewer:
        me = summary(mine)
        waiting = [i for i in await _assignments(database, person_id, now) if i["state"] != "done"]
        me["calls_left"] = len(waiting)
        me["lines_left"] = sum(LINES - i["handled"] for i in waiting)
        days = Counter(_day(r.created_at) for r in mine)
        me["daily"] = [
            {
                "date": (today - timedelta(days=n)).isoformat(),
                "labels": days[today - timedelta(days=n)],
            }
            for n in range(13, -1, -1)
        ]

    # Per line: agreement with the AI, what the AI said, and how far scores moved.
    per: dict[str, dict[str, Any]] = {}
    status_coverage: Counter[str] = Counter()
    for r in heads:
        if not judged(r):
            continue
        payload = r.payload or {}
        entry = per.setdefault(
            r.target,
            {
                "agree": 0,
                "partly": 0,
                "disagree": 0,
                "scored": 0,
                "gaps": [],
                "ai_status": Counter(),
                "status_changed": 0,
                "reasons": Counter(),
            },
        )
        if payload.get("verdict") in ("agree", "partly", "disagree"):
            entry[payload["verdict"]] += 1
        raw_ai = payload.get("ai")
        ai: dict[str, Any] = raw_ai if isinstance(raw_ai, dict) else {}
        if type(payload.get("score")) is int:
            entry["scored"] += 1
            if type(ai.get("score")) is int:
                entry["gaps"].append(abs(payload["score"] - ai["score"]))
        if isinstance(ai.get("status"), str):
            entry["ai_status"][ai["status"]] += 1
            status_coverage[ai["status"]] += 1
            if isinstance(payload.get("status"), str) and payload["status"] != ai["status"]:
                entry["status_changed"] += 1
        for reason in payload.get("reasons") or []:
            if isinstance(reason, str):
                entry["reasons"][reason] += 1
    pointers = []
    for target, label in labels.items():
        line = per.get(target) or {
            "agree": 0,
            "partly": 0,
            "disagree": 0,
            "scored": 0,
            "gaps": [],
            "ai_status": Counter(),
            "status_changed": 0,
            "reasons": Counter(),
        }
        n = line["agree"] + line["partly"] + line["disagree"]
        pointers.append(
            {
                "target": target,
                "label": label,
                "labels": max(n, line["scored"]),
                "agree": line["agree"],
                "partly": line["partly"],
                "disagree": line["disagree"],
                "agreement": _rate(line["agree"], line["partly"], line["disagree"]),
                "wrong_rate": round(line["disagree"] / n, 3) if n else None,
                "mean_score_gap": round(statistics.mean(line["gaps"]), 1) if line["gaps"] else None,
                "status_changed": line["status_changed"],
                "ai_status": dict(line["ai_status"]),
                "top_reasons": [k for k, _ in line["reasons"].most_common(3)],
            }
        )
    wrong_most = sorted(
        (p for p in pointers if p["labels"]),
        key=lambda p: ((p["wrong_rate"] or 0), -(p["agreement"] or 1), p["labels"]),
        reverse=True,
    )[:8]

    # Two reviewers on the same call and line: do they give the same verdict?
    by_line: dict[tuple[UUID, str], dict[UUID, str]] = defaultdict(dict)
    for r in heads:
        verdict = (r.payload or {}).get("verdict")
        if judged(r) and isinstance(verdict, str):
            by_line[(r.recording_id, r.target)][r.reviewer_id] = verdict
    pair_lines = {key: v for key, v in by_line.items() if len(v) >= 2}
    differ_by_target: Counter[str] = Counter()
    pairs_by_target: Counter[str] = Counter()
    for (_, target), verdicts in pair_lines.items():
        pairs_by_target[target] += 1
        if len(set(verdicts.values())) > 1:
            differ_by_target[target] += 1
    between = {
        "calls": len({recording for recording, _ in pair_lines}),
        "lines": len(pair_lines),
        "differ": sum(differ_by_target.values()),
        "agreement": None
        if not pair_lines
        else round(1 - sum(differ_by_target.values()) / len(pair_lines), 3),
        "by_line": [
            {
                "target": target,
                "label": labels.get(target, target),
                "lines": pairs_by_target[target],
                "differ": differ_by_target[target],
            }
            for target, _ in differ_by_target.most_common(8)
        ],
    }

    team = summary(heads)
    team["reviewers"] = len({r.reviewer_id for r in heads})
    team["calls_covered"] = len({r.recording_id for r in heads if judged(r)})
    result: dict[str, Any] = {
        "scope": "owner" if owner else "reviewer",
        "as_of": now.isoformat(),
        "me": me,
        "team": team,
        "pointers": pointers,
        "wrong_most": [p["target"] for p in wrong_most],
        "ai_status_coverage": dict(status_coverage),
        "between_reviewers": between,
        "truncated": len(rows) >= MAX_ROWS,
    }
    if owner:
        emails = {
            person.id: person.email
            for person in (
                await database.scalars(
                    select(Person).where(Person.id.in_({r.reviewer_id for r in heads}))
                )
            ).all()
        }
        by_reviewer: dict[UUID, list[GoldRow]] = defaultdict(list)
        for r in heads:
            by_reviewer[r.reviewer_id].append(r)
        result["reviewers"] = [
            {"email": emails.get(reviewer_id), **summary(selected)}
            for reviewer_id, selected in sorted(by_reviewer.items(), key=lambda item: -len(item[1]))
        ]
    return result
