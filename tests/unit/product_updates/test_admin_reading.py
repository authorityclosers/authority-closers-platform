"""Admin's read-only product notes list (AUT-1798): newest version per note."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from ac_platform.product_updates.admin_reading import latest_notes


def _note(key: str, version: int, day: int) -> SimpleNamespace:
    return SimpleNamespace(
        note_key=key,
        version=version,
        title=f"{key} v{version}",
        items=["One change"],
        note_date=date(2026, 10, day),
        audience="everyone",
        status="published" if version > 1 else "draft",
        major=False,
        release_id="rel-1",
        source_pr=441,
        created_by="deploy",
        published_at=datetime(2026, 10, day, tzinfo=UTC) if version > 1 else None,
    )


class _Database:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    async def scalars(self, _statement: object) -> Any:
        return SimpleNamespace(all=lambda: self.rows)


@pytest.mark.asyncio
async def test_latest_notes_keeps_the_newest_version_newest_first() -> None:
    result = await latest_notes(
        _Database([_note("a", 1, 9), _note("a", 2, 9), _note("b", 1, 10)])  # type: ignore[arg-type]
    )
    assert [(note["key"], note["version"]) for note in result["notes"]] == [("b", 1), ("a", 2)]
    assert result["notes"][1]["status"] == "published"
    assert result["notes"][0]["published_at"] is None
