"""Release writer replay, approvals, append-only history and atomic failure on PostgreSQL."""

import json
import os
import subprocess
import sys

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.product_updates.deploy import load_notes, successor, write_notes
from ac_platform.product_updates.models import ProductUpdate
from tests.integration.test_product_updates_postgresql import (
    updates_engine as updates_engine,  # noqa: F401
)

SHA = "a" * 40


def note(pr: int, *, approved: bool = False) -> dict:
    return {
        "key": f"pr-{pr}",
        "pr": pr,
        "merged_at": "2026-10-01T14:00:00Z",
        "title": "Fictional report update",
        "items": ["Read a fictional report summary."],
        "feature_key": None,
        "approved": approved,
    }


def notes_file(tmp_path, notes, *, release=SHA, complete=True):
    path = tmp_path / "product-notes.json"
    path.write_text(
        json.dumps({"version": 1, "release_sha": release, "complete": complete, "notes": notes})
    )
    return path


async def apply(engine: Engine, notes: list[dict], *, release=SHA) -> dict[str, int]:
    asynchronous = create_async_engine(engine.url)
    try:
        async with async_sessionmaker(asynchronous)() as database, database.begin():
            return await write_notes(database, notes, environment="staging", release_id=release)
    finally:
        await asynchronous.dispose()


def lineage(engine: Engine, pr: int):
    with Session(engine) as database:
        return database.scalars(
            select(ProductUpdate)
            .where(ProductUpdate.note_key == f"pr-{pr}")
            .order_by(ProductUpdate.version)
        ).all()


async def test_first_run_and_replay_preserve_history(updates_engine: Engine) -> None:
    assert await apply(updates_engine, [note(10001), note(10002, approved=True)]) == {
        "inserted": 2,
        "approved": 1,
        "published": 1,
    }
    drafts, published = lineage(updates_engine, 10001), lineage(updates_engine, 10002)
    assert [(r.version, r.status) for r in drafts] == [(1, "draft")]
    assert [(r.version, r.status) for r in published] == [(1, "approved"), (2, "published")]
    assert published[1].supersedes_id == published[0].id
    assert published[1].published_at is not None and published[0].published_at is None
    assert all(r.created_by == "deploy" and r.release_id == SHA for r in drafts + published)
    assert published[0].note_date.isoformat() == "2026-10-01"
    before = [(r.id, r.created_at, r.title, r.items) for r in drafts + published]
    assert await apply(updates_engine, [note(10001), note(10002, approved=True)]) == {
        "inserted": 0,
        "approved": 0,
        "published": 0,
    }
    assert [
        (r.id, r.created_at, r.title, r.items)
        for r in lineage(updates_engine, 10001) + lineage(updates_engine, 10002)
    ] == before


async def test_later_label_approves_then_publishes_without_rewriting_text(
    updates_engine: Engine,
) -> None:
    await apply(updates_engine, [note(10003)])
    assert await apply(updates_engine, [note(10003, approved=True)], release="b" * 40) == {
        "inserted": 0,
        "approved": 1,
        "published": 1,
    }
    rows = lineage(updates_engine, 10003)
    assert [(r.version, r.status) for r in rows] == [
        (1, "draft"),
        (2, "approved"),
        (3, "published"),
    ]
    assert rows[1].supersedes_id == rows[0].id and rows[2].supersedes_id == rows[1].id
    assert all(
        r.release_id == SHA and r.title == rows[0].title and r.items == rows[0].items for r in rows
    )


async def test_admin_edit_and_changed_pr_text_are_left_alone(updates_engine: Engine) -> None:
    await apply(updates_engine, [note(10004), note(10005)])
    with Session(updates_engine) as database, database.begin():
        original = database.scalars(
            select(ProductUpdate).where(ProductUpdate.note_key == "pr-10004")
        ).one()
        edited = successor(original, "draft")
        edited.created_by = "admin"
        edited.title = "Fictional Admin wording"
        database.add(edited)
    changed = note(10005, approved=True) | {"items": ["A different fictional summary."]}
    assert await apply(updates_engine, [note(10004, approved=True), changed]) == {
        "inserted": 0,
        "approved": 0,
        "published": 0,
    }
    assert [r.status for r in lineage(updates_engine, 10004)] == ["draft", "draft"]
    assert lineage(updates_engine, 10004)[1].title == "Fictional Admin wording"
    assert len(lineage(updates_engine, 10005)) == 1


async def test_approved_lineage_outside_collection_is_published(updates_engine: Engine) -> None:
    await apply(updates_engine, [note(10006)])
    with Session(updates_engine) as database, database.begin():
        previous = database.scalars(
            select(ProductUpdate).where(ProductUpdate.note_key == "pr-10006")
        ).one()
        approval = successor(previous, "approved")
        approval.created_by = "admin"
        approval.audience, approval.major = "testers", True
        database.add(approval)
    assert await apply(updates_engine, []) == {"inserted": 0, "approved": 0, "published": 1}
    rows = lineage(updates_engine, 10006)
    assert rows[-1].status == "published" and rows[-1].audience == "testers" and rows[-1].major


async def test_failed_transaction_does_not_leave_partial_lineages(updates_engine: Engine) -> None:
    invalid = note(10008) | {"title": "x" * 61}
    with pytest.raises(IntegrityError):
        await apply(updates_engine, [note(10007), invalid])
    assert lineage(updates_engine, 10007) == lineage(updates_engine, 10008) == []


def test_cli_uses_migrator_connection_and_prints_only_counts(
    updates_engine: Engine, tmp_path
) -> None:
    path = notes_file(tmp_path, [note(10009, approved=True)])
    environment = os.environ | {
        "AC_DATABASE_MIGRATOR_URL": updates_engine.url.render_as_string(hide_password=False),
        "AC_DATABASE_URL": "deliberately-invalid-runtime-url",
    }
    argv = [
        sys.executable,
        "-m",
        "ac_platform.product_updates.deploy",
        "--environment",
        "production",
        "--release-id",
        SHA,
        "--notes",
        str(path),
    ]
    first = subprocess.run(argv, env=environment, capture_output=True, text=True, check=False)  # noqa: S603 - fixed CLI and fictional inputs
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout) == {"inserted": 1, "approved": 1, "published": 1}
    assert first.stderr == "" and "Fictional" not in first.stdout
    second = subprocess.run(argv, env=environment, capture_output=True, text=True, check=False)  # noqa: S603 - fixed CLI and fictional inputs
    assert second.returncode == 0 and json.loads(second.stdout) == {
        "inserted": 0,
        "approved": 0,
        "published": 0,
    }


def test_cli_refuses_unknown_environment(tmp_path) -> None:
    from ac_platform.product_updates.deploy import main

    with pytest.raises(SystemExit) as error:
        main(["--environment", "unknown", "--release-id", SHA, "--notes", str(tmp_path / "absent")])
    assert error.value.code == 2


def test_envelope_rejects_wrong_release_and_duplicate_keys(tmp_path) -> None:
    with pytest.raises(ValueError, match="bound"):
        load_notes(notes_file(tmp_path, [note(1)], release="b" * 40), SHA)
    with pytest.raises(ValueError, match="duplicate"):
        load_notes(notes_file(tmp_path, [note(1), note(1)]), SHA)
    assert load_notes(notes_file(tmp_path, [], release=""), SHA) == []
    assert load_notes(notes_file(tmp_path, [note(1)], complete=False), SHA) == []
