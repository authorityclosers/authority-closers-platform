"""New leads through the duplicate engine as they arrive: a certain pair is merged by the desk,
any other pair waits for review, and nothing runs while another scan holds the organisation."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from ac_platform.lead_desk import duplicate_intake, duplicate_scan, merging
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.store import LeadDesk, Viewer

NEW, OLD, OTHER, THIRD = uuid4(), uuid4(), uuid4(), uuid4()


@dataclass
class Db:
    pairs: list[Any] = field(default_factory=list)
    savepoints: int = 0

    async def scalars(self, statement: Any) -> Any:
        return SimpleNamespace(all=lambda: self.pairs)

    @asynccontextmanager
    async def begin_nested(self) -> Any:
        self.savepoints += 1
        yield


def pair(first: UUID, second: UUID, band: str) -> SimpleNamespace:
    return SimpleNamespace(first_lead_id=first, second_lead_id=second, band=band)


def desk(db: Db, person: UUID | None = None) -> LeadDesk:
    viewer = Viewer(person_id=person or uuid4(), tenant_id=uuid4(), role="system", name="Meta")
    return LeadDesk(db, viewer, now=datetime(2027, 1, 15, tzinfo=UTC))  # type: ignore[arg-type]


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {"locked": True, "scans": 0, "merges": [], "refuse": set()}

    async def lock(db: Any, tenant_id: UUID) -> bool:
        return bool(seen["locked"])

    async def scan(db: Any, tenant_id: UUID, now: datetime) -> dict[str, Any]:
        seen["scans"] += 1
        return {}

    async def merge(manager: LeadDesk, command: Any) -> None:
        assert manager.viewer.can_manage and manager.viewer.role == "admin"
        if set(command.lead_ids) & seen["refuse"]:
            raise DeskError(409, "One of these leads was merged already.")
        seen["merges"].append(command)

    monkeypatch.setattr(duplicate_scan, "lock", lock)
    monkeypatch.setattr(duplicate_scan, "scan", scan)
    monkeypatch.setattr(merging, "merge", merge)
    return seen


def test_a_certain_pair_with_a_new_lead_is_merged_and_the_rest_wait_for_review(
    engine: dict[str, Any],
) -> None:
    db = Db(pairs=[pair(OLD, NEW, "certain"), pair(NEW, OTHER, "probable")])
    done = asyncio.run(duplicate_intake.after_intake(desk(db), [NEW]))
    assert done == duplicate_intake.Checked(merged=1, queued=1)
    [command] = engine["merges"]
    assert command.lead_ids == (OLD, NEW) and db.savepoints == 1 and engine["scans"] == 1


def test_a_merge_that_cannot_go_ahead_leaves_the_pair_for_review(engine: dict[str, Any]) -> None:
    engine["refuse"] = {THIRD}
    db = Db(pairs=[pair(THIRD, NEW, "certain")])
    assert asyncio.run(duplicate_intake.after_intake(desk(db), [NEW])) == duplicate_intake.Checked(
        merged=0, queued=1
    )


def test_nothing_runs_without_new_leads_or_while_another_scan_holds_the_organisation(
    engine: dict[str, Any],
) -> None:
    db = Db(pairs=[pair(OLD, NEW, "certain")])
    assert asyncio.run(duplicate_intake.after_intake(desk(db), [])) == duplicate_intake.Checked()
    engine["locked"] = False
    assert asyncio.run(duplicate_intake.after_intake(desk(db), [NEW])) == duplicate_intake.Checked()
    assert engine["scans"] == 0 and engine["merges"] == []


def test_the_merge_command_is_the_same_for_the_same_pair(engine: dict[str, Any]) -> None:
    db = Db(pairs=[pair(OLD, NEW, "certain")])
    one = desk(db)
    asyncio.run(duplicate_intake.after_intake(one, [NEW]))
    asyncio.run(duplicate_intake.after_intake(one, [NEW]))
    first, second = engine["merges"]
    assert first.command_id == second.command_id
