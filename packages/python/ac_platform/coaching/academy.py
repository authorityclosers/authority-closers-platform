"""Resolve an explicitly reviewed course link against the existing public API.

No title-based course guessing, enrollment, grant, progress or payment writes.
The caller supplies its configured Academy API read helper; unavailable/older
routes return a small unavailable result rather than breaking Coaching.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID

from pydantic import Field, ValidationError

from ac_platform.coaching.contracts import Model
from ac_platform.http.course import ProgramDetailResponse


class AcademyReference(Model):
    program_id: UUID
    program_version_id: UUID
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,119}$")
    module_id: UUID | None = None
    activity_id: UUID | None = None
    mapping_review_reference: str = Field(min_length=1, max_length=256)


class AcademyTarget(Model):
    program_id: UUID
    program_version_id: UUID
    title: str
    course_path: str
    module_id: UUID | None
    activity_id: UUID | None
    lesson_path: str | None
    mapping_review_reference: str


class AcademyRead(Model):
    target: AcademyTarget | None
    error: str | None = None


async def resolve_academy_target(
    reference: AcademyReference,
    read_json: Callable[[str], Awaitable[dict[str, Any] | None]],
) -> AcademyRead:
    """Use published programs/modules/activities; pin the reviewed version.

    The helper must fetch from the configured Academy API, whose public program
    endpoint excludes unpublished/private courses. A changed version requires a
    fresh mapping review; the old mapping is not silently forwarded.
    """
    try:
        payload = await read_json(f"/v1/programs/{quote(reference.slug, safe='')}")
    except Exception:
        return AcademyRead(target=None, error="The Academy catalogue is temporarily unavailable.")
    if payload is None:
        return AcademyRead(target=None, error="The matching Academy course is unavailable.")
    try:
        program = ProgramDetailResponse.model_validate(payload)
        published_at = datetime.fromisoformat(program.published_at.replace("Z", "+00:00"))
        if (
            program.id != reference.program_id
            or program.program_version_id != reference.program_version_id
            or program.slug != reference.slug
            or published_at.tzinfo is None
            or not program.title.strip()
        ):
            raise ValueError("The reviewed course revision changed.")
        module = next((m for m in program.modules if m.id == reference.module_id), None)
        if reference.module_id is not None and module is None:
            raise ValueError("The reviewed module is no longer present.")
        if reference.activity_id is not None and (
            module is None or not any(a.id == reference.activity_id for a in module.activities)
        ):
            raise ValueError("The reviewed activity is not part of the selected module.")
    except (ValidationError, ValueError):
        return AcademyRead(target=None, error="The course link needs a fresh catalogue review.")
    lesson_path = None
    if reference.activity_id is not None:
        lesson_path = f"/activity/{reference.activity_id}"
    elif reference.module_id is not None:
        lesson_path = f"/learn/{reference.slug}/module/{reference.module_id}"
    return AcademyRead(
        target=AcademyTarget(
            program_id=program.id,
            program_version_id=program.program_version_id,
            title=program.title,
            course_path=f"/programs/{program.slug}",
            module_id=reference.module_id,
            activity_id=reference.activity_id,
            lesson_path=lesson_path,
            mapping_review_reference=reference.mapping_review_reference,
        )
    )
