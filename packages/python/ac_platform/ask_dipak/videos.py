"""Ask Dipak's lesson videos: one switch and the approved videos, OFF until approved.

Owner, 19 Nov 2026 23:36 IST: "the videos are not approved for Ask Dipak, so make sure they
won't go live on the app in the next update". v1.88 showed the studio's PB03 and OB03 videos
with no switch and was rolled back. From now on a lesson shows a video only when:

- the switch is on (``admin.py ask-dipak videos on``), and
- that lesson has a video added (``admin.py ask-dipak add-video``), each one only after Dipak and
  the owner approve it.

Both live with Dipak's lessons, in the newest ``sales_xray_ask_dipak_library_versions`` row's
``source`` (``library.VIDEOS``): every change appends one row with the same lessons, the approver
and the issue, so the history is kept and an import of his docs carries the videos forward.
With no row, or no ``lesson_videos`` in it, the switch is off: a new environment (staging,
production) shows no video until someone turns it on as a recorded data change.

The app asks ``GET /v1/sales-xray/ask-dipak/videos`` once per visit and never keeps the answer,
so switching off takes effect at the next visit. The files are not in the web app's build; an
approved video is added with where it is served from.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.ask_dipak import catalogue, library
from ac_platform.ask_dipak.models import SalesXrayAskDipakLibraryVersion as Version

OFF: dict[str, Any] = {"enabled": False, "videos": {}}
MAX_SECONDS = 600
MAX_URL = 300
# A same-origin path ("/dev-media/...") or an https address; never "//host" or "..".
_URL = re.compile(r"^(/(?!/)[A-Za-z0-9._~/-]+|https://[A-Za-z0-9.-]+(/[A-Za-z0-9._~%/-]*)?)$")
_VIDEO = (".mp4",)
_POSTER = (".jpg", ".jpeg", ".png", ".webp")


class VideoError(ValueError):
    """A video or a stored state that is not one the app can show."""


def _url(value: Any, ends: tuple[str, ...], what: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_URL
        or not _URL.fullmatch(value)
        or ".." in value
        or not value.lower().endswith(ends)
    ):
        raise VideoError(f"{what} must be a /path or https:// address ending {'/'.join(ends)}")
    return value


def check_video(lesson: str, src: Any, poster: Any, seconds: Any) -> dict[str, Any]:
    """One lesson's video as stored and served, or VideoError."""
    if lesson not in catalogue.QUESTION_IDS:
        raise VideoError(f"{lesson} is not one of Dipak's questions")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= MAX_SECONDS:
        raise VideoError(f"seconds must be a whole number from 1 to {MAX_SECONDS}")
    return {
        "src": _url(src, _VIDEO, "src"),
        "poster": _url(poster, _POSTER, "poster"),
        "seconds": seconds,
    }


def state_of(source: Any) -> dict[str, Any]:
    """The switch and the videos in a row's source; anything unreadable is OFF."""
    raw = source.get(library.VIDEOS) if isinstance(source, Mapping) else None
    if not isinstance(raw, Mapping) or not isinstance(raw.get("videos"), Mapping):
        return {"enabled": False, "videos": {}}
    videos: dict[str, Any] = {}
    for lesson, video in raw["videos"].items():
        try:
            if not isinstance(video, Mapping):
                raise VideoError("not a video")
            videos[lesson] = check_video(
                lesson, video.get("src"), video.get("poster"), video.get("seconds")
            )
        except VideoError:
            continue
    return {"enabled": raw.get("enabled") is True, "videos": dict(sorted(videos.items()))}


async def _newest(db: AsyncSession) -> Version | None:
    return await db.scalar(  # type: ignore[no-any-return]
        select(Version).order_by(Version.created_at.desc(), Version.id.desc()).limit(1)
    )


async def current(db: AsyncSession) -> dict[str, Any]:
    """Where the switch and the videos stand (OFF with no row)."""
    row = await db.scalar(
        select(Version.source).order_by(Version.created_at.desc(), Version.id.desc()).limit(1)
    )
    return state_of(row)


async def served(db: AsyncSession) -> dict[str, Any]:
    """What the app may show: the videos when the switch is on, else none."""
    state = await current(db)
    return dict(state["videos"]) if state["enabled"] else {}


async def record(
    db: AsyncSession,
    *,
    state: Mapping[str, Any],
    approved_by: str,
    issue: str,
    note: str,
    now: datetime,
) -> dict[str, Any]:
    """Append the newest lessons again with ``state`` as their videos; the caller's transaction
    commits or rolls back. Returns before and after; nothing is written when they are equal."""
    after = state_of({library.VIDEOS: state})
    newest = await _newest(db)
    before = state_of(newest.source if newest is not None else None)
    if before == after:
        return {"status": "already_set", "before": before, "after": before}
    if newest is not None:
        lessons = dict(newest.lessons)
        source = dict(newest.source or {})
    else:
        lessons = dict(library.bundled().lessons)
        source = {"from": "bundled library.json"}
    library.check(lessons)
    if newest is not None and newest.created_at >= now:
        now = newest.created_at + timedelta(microseconds=1)  # stays the newest row
    source[library.VIDEOS] = after
    source["videos_note"] = note[:200]
    row = Version(
        id=uuid4(),
        content_sha256=library.content_sha256(lessons),
        lessons=lessons,
        source=source,
        lesson_count=len(lessons),
        approved_by=approved_by[:120],
        issue=issue[:120],
        created_at=now,
    )
    db.add(row)
    await db.flush()
    return {"status": "eligible", "before": before, "after": after, "row_id": str(row.id)}


__all__ = ["OFF", "VideoError", "check_video", "current", "record", "served", "state_of"]
