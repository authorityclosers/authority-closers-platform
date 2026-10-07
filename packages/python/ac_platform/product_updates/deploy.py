"""Append release-bound product notes and publish approvals in one transaction."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.db.models import model_metadata
from ac_platform.product_updates.models import ProductUpdate
from ac_platform.product_updates.pr_note import UserNote, parse_user_note

ENVIRONMENTS = ("development", "staging", "production")


def load_notes(path: Path, release_id: str) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("complete"), bool):
        raise ValueError("invalid notes envelope")
    notes = payload["notes"]
    if not isinstance(notes, list) or len(notes) > 200:
        raise ValueError("invalid notes list")
    if payload.get("release_sha") != release_id and not (
        payload.get("release_sha") == "" and not notes
    ):
        raise ValueError("notes are not bound to this release")
    if not payload["complete"]:
        return []
    keys = set()
    for note in notes:
        pr = note["pr"]
        if type(pr) is not int or pr <= 0 or note["key"] != f"pr-{pr}" or note["key"] in keys:
            raise ValueError("invalid or duplicate PR lineage")
        keys.add(note["key"])
        if not isinstance(note["title"], str) or not isinstance(note["items"], list):
            raise ValueError("invalid note text")
        feature = note["feature_key"]
        if feature is not None and not isinstance(feature, str):
            raise ValueError("invalid feature key")
        if not all(isinstance(item, str) for item in note["items"]):
            raise ValueError("invalid note items")
        body = "## User-facing note\nTitle: " + note["title"]
        body += "\n" + "\n".join("- " + item for item in note["items"])
        if feature is not None:
            body += "\nFeature: " + feature
        parsed = parse_user_note(body)
        if not isinstance(parsed, UserNote) or (parsed.title, parsed.items, parsed.feature_key) != (
            note["title"],
            note["items"],
            feature,
        ):
            raise ValueError("invalid note format")
        if type(note["approved"]) is not bool:
            raise ValueError("invalid approval")
        merged_at = datetime.fromisoformat(note["merged_at"])
        if merged_at.tzinfo is None:
            raise ValueError("merge time must name a timezone")
    return notes


def successor(previous: ProductUpdate, status: str) -> ProductUpdate:
    return ProductUpdate(
        note_key=previous.note_key,
        version=previous.version + 1,
        supersedes_id=previous.id,
        release_id=previous.release_id,
        source_pr=previous.source_pr,
        note_date=previous.note_date,
        title=previous.title,
        items=list(previous.items),
        feature_key=previous.feature_key,
        audience=previous.audience,
        major=previous.major,
        status=status,
        created_by="deploy",
        published_at=datetime.now(UTC) if status == "published" else None,
    )


async def write_notes(
    database: AsyncSession, notes: list[dict[str, Any]], *, environment: str, release_id: str
) -> dict[str, int]:
    if environment not in ENVIRONMENTS or not re.fullmatch(r"[0-9a-f]{40}", release_id):
        raise ValueError("unknown environment or invalid release ID")
    # Serialize deploy writers; the unique successor constraint also protects Admin races.
    await database.execute(text("SELECT pg_advisory_xact_lock(471, 1)"))
    latest = {
        note.note_key: note
        for note in await database.scalars(select(ProductUpdate).order_by(ProductUpdate.version))
    }
    counts = {"inserted": 0, "approved": 0, "published": 0}
    for note in notes:
        previous = latest.get(note["key"])
        if previous is None:
            previous = ProductUpdate(
                note_key=note["key"],
                version=1,
                release_id=release_id,
                source_pr=note["pr"],
                note_date=datetime.fromisoformat(note["merged_at"]).astimezone(UTC).date(),
                title=note["title"],
                items=note["items"],
                feature_key=note["feature_key"],
                status="approved" if note["approved"] else "draft",
                created_by="deploy",
            )
            database.add(previous)
            await database.flush()
            counts["inserted"] += 1
            counts["approved"] += int(note["approved"])
        elif (
            note["approved"]
            and previous.status == "draft"
            and previous.created_by == "deploy"
            and (previous.title, previous.items, previous.feature_key)
            == (note["title"], note["items"], note["feature_key"])
        ):
            previous = successor(previous, "approved")
            database.add(previous)
            await database.flush()
            counts["approved"] += 1
        latest[note["key"]] = previous
    for previous in latest.values():
        if previous.status == "approved":
            database.add(successor(previous, "published"))
            counts["published"] += 1
    await database.flush()
    return counts


async def deploy(environment: str, release_id: str, path: Path) -> dict[str, int]:
    notes = load_notes(path, release_id)
    model_metadata()
    database_url = os.environ.get("AC_DATABASE_MIGRATOR_URL") or os.environ["AC_DATABASE_URL"]
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine)() as database, database.begin():
            return await write_notes(
                database, notes, environment=environment, release_id=release_id
            )
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=ENVIRONMENTS)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--notes", type=Path, default=Path("/app/product-notes.json"))
    args = parser.parse_args(argv)
    try:
        counts = asyncio.run(deploy(args.environment, args.release_id, args.notes))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, SQLAlchemyError):
        print("Product note writer failed; no note changes were committed.", file=sys.stderr)
        return 1
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
