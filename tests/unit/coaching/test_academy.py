"""Reviewed Academy mappings use exact existing program/module/activity IDs."""

import asyncio
from uuid import UUID

import pytest

from ac_platform.coaching.academy import AcademyReference, resolve_academy_target


def reference() -> AcademyReference:
    return AcademyReference(
        program_id=UUID(int=1),
        program_version_id=UUID(int=2),
        slug="fictional-impact-course",
        module_id=UUID(int=3),
        activity_id=UUID(int=4),
        mapping_review_reference="fictional-review",
    )


def course():
    return {
        "id": str(UUID(int=1)),
        "program_version_id": str(UUID(int=2)),
        "slug": "fictional-impact-course",
        "title": "Fictional impact course",
        "version_number": 1,
        "published_at": "2026-10-10T09:00:00Z",
        "modules": [
            {
                "id": str(UUID(int=3)),
                "title": "Fictional module",
                "position": 0,
                "prerequisite_module_ids": [],
                "activities": [
                    {
                        "id": str(UUID(int=4)),
                        "title": "Fictional lesson",
                        "position": 0,
                        "kind": "VIDEO",
                        "is_required": True,
                    }
                ],
            }
        ],
    }


def resolve(mapping: AcademyReference, payload):
    async def read(path: str):
        assert path == "/v1/programs/fictional-impact-course"
        return payload

    return asyncio.run(resolve_academy_target(mapping, read))


def test_exact_published_course_and_lesson_are_linked_without_enrollment_or_grants() -> None:
    result = resolve(reference(), course())
    assert result.error is None
    assert result.target.course_path == "/programs/fictional-impact-course"
    assert result.target.lesson_path == f"/activity/{UUID(int=4)}"
    assert result.target.program_version_id == UUID(int=2)


@pytest.mark.parametrize("change", ["version", "program", "module", "activity", "missing"])
def test_stale_missing_and_cross_course_links_remain_unavailable(change: str) -> None:
    payload = course()
    if change == "version":
        payload["program_version_id"] = str(UUID(int=999))
    elif change == "program":
        payload["id"] = str(UUID(int=999))
    elif change == "module":
        payload["modules"][0]["id"] = str(UUID(int=999))
    elif change == "activity":
        payload["modules"][0]["activities"] = []
    else:
        payload = {}
    result = resolve(reference(), payload)
    assert result.target is None and result.error


def test_missing_route_or_timed_out_read_does_not_crash_coaching() -> None:
    assert resolve(reference(), None).target is None

    async def timed_out(path: str):
        raise TimeoutError()

    result = asyncio.run(resolve_academy_target(reference(), timed_out))
    assert result.target is None and "temporarily unavailable" in result.error
