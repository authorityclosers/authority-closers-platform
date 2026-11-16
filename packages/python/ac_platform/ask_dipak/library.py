"""Dipak's lessons as served: the newest import in the database, else the bundled library.

The owner (16 Nov 2026) wants Dipak's edits to reach the app as "a database update kind of
situation". An import of his ten docs (scripts/data-changes/ask-dipak-import-lessons.py,
dry run by default) appends one ``sales_xray_ask_dipak_library_versions`` row holding every
lesson word for word; the newest row is what the app, the API, MCP and the CLI teach. Until
the first import, the library.json bundled with the code is served, so a new environment
works with no data step.

The question ids and categories stay in code (catalogue.py): an import replaces the lessons
of Dipak's 150 questions and their titles on the lesson screen, and refuses anything else.
Each lesson's report and coaching consistency lock stays on the server (``seller_view`` drops
it) for Sales X-Ray's reports.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.ask_dipak import catalogue
from ac_platform.ask_dipak.models import SalesXrayAskDipakLibraryVersion as Version

#: The fields every lesson has, in the app's format (scripts/ask-dipak/import_dipak_docs.py).
REQUIRED = ("quick", "scenario", "options", "deep", "cue", "mission", "next")
#: Server-only fields: never in what a seller's screen or a key receives.
SERVER_ONLY = frozenset({"lock"})


class LibraryError(ValueError):
    """An import that is not a whole library of Dipak's 150 lessons."""


def content_sha256(lessons: Mapping[str, Any]) -> str:
    """The hash of the lessons in canonical JSON (keys sorted, no spaces)."""
    canonical = json.dumps(lessons, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Served:
    """The library being served: its version (a short content hash) and its lessons."""

    version: str
    lessons: Mapping[str, Any]
    imported_at: datetime | None = None


@cache
def bundled() -> Served:
    lessons = catalogue.bundled_lessons()
    return Served(version=content_sha256(lessons)[:16], lessons=lessons)


#: The newest row's lessons, kept per process: rows are written once, so an id never changes.
_LOADED: dict[UUID, Served] = {}


async def served(db: AsyncSession) -> Served:
    """The newest imported library, else the bundled one. One small read per call; the
    lessons themselves are read once per process and row."""
    newest = (
        await db.execute(
            select(Version.id, Version.content_sha256, Version.created_at)
            .order_by(Version.created_at.desc(), Version.id.desc())
            .limit(1)
        )
    ).first()
    if newest is None:
        found = bundled()
    else:
        row_id, sha, created_at = newest
        if row_id not in _LOADED:
            lessons = await db.scalar(select(Version.lessons).where(Version.id == row_id))
            _LOADED.clear()
            _LOADED[row_id] = Served(
                version=sha[:16], lessons=lessons or {}, imported_at=created_at
            )
        found = _LOADED[row_id]
    catalogue.use_lessons(found.lessons)
    return found


def seller_view(lesson: Mapping[str, Any]) -> dict[str, Any]:
    """A lesson as the app shows it: everything but the server-only lock."""
    return {key: value for key, value in lesson.items() if key not in SERVER_ONLY}


def check(lessons: Mapping[str, Any]) -> None:
    """Refuse an import that is not one whole lesson for each of Dipak's 150 questions."""
    ids = set(lessons)
    if ids != set(catalogue.QUESTION_IDS):
        missing = sorted(set(catalogue.QUESTION_IDS) - ids)
        extra = sorted(ids - set(catalogue.QUESTION_IDS))
        raise LibraryError(f"lessons must be Dipak's 150: missing {missing}, unknown {extra}")
    for code, lesson in lessons.items():
        absent = [field for field in REQUIRED if not lesson.get(field)]
        if absent:
            raise LibraryError(f"{code}: empty {absent}")
        options = lesson["options"]
        if len(options) != 3 or any(len(option) < 3 or not all(option[:3]) for option in options):
            raise LibraryError(f"{code}: options must be three [choice, word, takeaway]")
        unknown = [code_ for code_ in lesson["next"] if code_ not in catalogue.QUESTION_IDS]
        if unknown:
            raise LibraryError(f"{code}: next questions {unknown} are not Dipak's")


async def record_import(
    db: AsyncSession,
    *,
    lessons: Mapping[str, Any],
    source: Mapping[str, Any],
    approved_by: str,
    issue: str,
    now: datetime,
    apply: bool,
) -> dict[str, Any]:
    """Append an import as the newest library, unless it equals the newest already.

    Returns before and after (version, lesson count, what changed); writes only with
    ``apply``. The caller owns the transaction."""
    check(lessons)
    sha = content_sha256(lessons)
    current = await served(db)
    changed = sorted(code for code in lessons if current.lessons.get(code) != lessons[code])
    result: dict[str, Any] = {
        "before": {
            "version": current.version,
            "from": "bundled" if current.imported_at is None else "database",
            "lessons": len(current.lessons),
        },
        "after": {"version": sha[:16], "lessons": len(lessons)},
        "changed_lessons": changed,
        "unchanged": sha[:16] == current.version,
        "applied": False,
    }
    if result["unchanged"] or not apply:
        return result
    row = Version(
        id=uuid4(),
        content_sha256=sha,
        lessons=dict(lessons),
        source=dict(source),
        lesson_count=len(lessons),
        approved_by=approved_by,
        issue=issue,
        created_at=now,
    )
    db.add(row)
    await db.flush()
    result["applied"] = True
    result["row_id"] = str(row.id)
    return result


__all__ = [
    "REQUIRED",
    "SERVER_ONLY",
    "LibraryError",
    "Served",
    "bundled",
    "check",
    "content_sha256",
    "record_import",
    "seller_view",
    "served",
]
