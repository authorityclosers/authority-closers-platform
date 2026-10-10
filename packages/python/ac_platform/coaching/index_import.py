"""Read-only AC Drive metadata triage; unknown content never becomes teaching.

The exported index has no owners, contents, durations or immutable Drive content
revisions. Its snapshot hash binds metadata review only. These candidates cannot
be converted to an approved LearningAsset or used as a lesson recommendation.
"""

import argparse
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from ac_platform.coaching.catalogue import Category
from ac_platform.coaching.contracts import GapType, Model
from ac_platform.conversation_intelligence.checkpoints import content_hash

INDEX_COLUMNS = frozenset(
    {"id", "source", "path", "name", "is_dir", "mime", "size", "modified", "category", "project"}
)
SOURCE_CATEGORIES = (
    "Coach content",
    "Coach content (Dipak)",
    "Courses",
    "Content library",
    "Sales training recordings",
    "Sales",
)


class MediaCandidate(Model):
    drive_id: str = Field(pattern=r"^[A-Za-z0-9_-]{10,200}$")
    index_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: str = Field(min_length=1, max_length=128)
    source_path: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=256)
    mime: str
    modified_at: datetime | None
    source_category: str
    proposed_category: Category | None
    kind: Literal["audio", "video"]
    # Explicit unknowns: filenames and folder labels do not prove these facts.
    content_revision: None = None
    duration_seconds: None = None
    dipak_confirmed: Literal[False] = False
    skill_ids: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    gap_types: tuple[GapType, ...] = ("uncertain",)
    status: Literal["needs_content_review"] = "needs_content_review"
    triage_reference: Literal["AUT-1678-index-metadata-v1"] = "AUT-1678-index-metadata-v1"
    reason: str = (
        "Metadata cannot establish a teachable skill, gap type, creator, duration or rights. "
        "Review the exact content revision and provenance before tagging or recommending."
    )


def read_candidates(index: Path) -> tuple[MediaCandidate, ...]:
    """No index writes, guessed Drive lookup, source download or provider request."""
    if not index.is_file():
        raise ValueError("An exported read-only AC Drive index is required.")
    with sqlite3.connect(index.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        columns = frozenset(row["name"] for row in db.execute("PRAGMA table_info(files)"))
        if not columns.issuperset(INDEX_COLUMNS):
            raise ValueError("The exported index schema is unsupported.")
        rows = db.execute(
            "SELECT id, source, path, name, mime, modified, category FROM files "
            "WHERE is_dir=0 AND (mime LIKE 'audio/%' OR mime LIKE 'video/%') "
            "AND category IN (?, ?, ?, ?, ?, ?) ORDER BY id",
            SOURCE_CATEGORIES,
        ).fetchall()
    result = []
    for row in rows:
        category = row["category"]
        # The owner's exported label explicitly names Coach content. Broad
        # Sales remains unresolved unless the path itself names training.
        proposed: Category | None = None
        if category in {"Coach content", "Coach content (Dipak)"}:
            proposed = "Coach content"
        elif category == "Courses":
            proposed = "Courses"
        elif category == "Content library":
            proposed = "Content library"
        elif category == "Sales training recordings" or (
            category == "Sales" and "training" in row["path"].casefold()
        ):
            proposed = "Sales training recordings"
        modified = (
            datetime.fromisoformat(row["modified"].replace("Z", "+00:00"))
            if row["modified"]
            else None
        )
        result.append(
            MediaCandidate(
                drive_id=row["id"],
                index_revision=content_hash(dict(row)),
                source=row["source"],
                source_path=row["path"],
                title=row["name"],
                mime=row["mime"],
                modified_at=modified,
                source_category=category,
                proposed_category=proposed,
                kind="audio" if row["mime"].startswith("audio/") else "video",
                topics=("sales training",) if proposed == "Sales training recordings" else (),
            )
        )
    if len({item.drive_id for item in result}) != len(result):
        raise ValueError("The exported index contains duplicate Drive identities.")
    return tuple(result)


def write_review_package(index: Path, output: Path) -> int:
    """A private proposal package, not a canonical product review queue."""
    candidates = read_candidates(index)
    payload = {
        "schema": "ac.sales-xray.coaching-media-proposal-package/1",
        "canonical": False,
        "provider_calls": 0,
        "status": "needs_content_review",
        "candidates": [item.model_dump(mode="json") for item in candidates],
    }
    # Refuse overwrite: subsequent triage supersedes a previous package.
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        json.dump(payload, target, ensure_ascii=False, indent=2)
        target.write("\n")
    return len(candidates)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    count = write_review_package(arguments.index, arguments.output)
    print(json.dumps({"candidates": count, "canonical": False, "provider_calls": 0}))


if __name__ == "__main__":
    main()
