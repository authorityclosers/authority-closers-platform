"""Index fixtures are invented; real metadata and call content never enter Git."""

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from ac_platform.coaching.index_import import read_candidates, write_review_package


def index(path: Path) -> Path:
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE files (id TEXT, source TEXT, path TEXT, name TEXT, is_dir INT, "
            "mime TEXT, size INT, modified TEXT, category TEXT, project TEXT)"
        )
        for identifier, name, mime, category, folder in (
            ("fictional_audio_123", "Audio.mp3", "audio/mpeg", "Coach content (Dipak)", "Coach"),
            ("fictional_video_123", "Lesson.mp4", "video/mp4", "Sales", "Sales training"),
            ("fictional_unknown_123", "Unknown.mp4", "video/mp4", "Sales", "Unknown"),
            ("fictional_doc_123", "Guide.docx", "application/msword", "Courses", "Course"),
            ("fictional_other_123", "Other.mp4", "video/mp4", "Other project", "Other"),
        ):
            db.execute(
                "INSERT INTO files VALUES (?, 'fictional-index', ?, ?, 0, ?, 100, "
                "'2026-10-10T00:00:00Z', ?, '')",
                (identifier, f"{folder}/{name}", name, mime, category),
            )
    return path


def test_read_only_metadata_proposals_cannot_invent_skills_creator_duration_or_category(
    tmp_path: Path,
) -> None:
    source = index(tmp_path / "source.db")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    rows = read_candidates(source)
    assert len(rows) == 3
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert all(row.status == "needs_content_review" and row.skill_ids == () for row in rows)
    assert all(row.content_revision is row.duration_seconds is None for row in rows)
    assert all(row.dipak_confirmed is False and row.gap_types == ("uncertain",) for row in rows)
    unknown = next(row for row in rows if row.drive_id == "fictional_unknown_123")
    assert unknown.proposed_category is None and unknown.topics == ()
    audio = next(row for row in rows if row.kind == "audio")
    assert audio.proposed_category == "Coach content"


def test_metadata_revision_changes_and_review_packages_supersede_instead_of_overwrite(
    tmp_path: Path,
) -> None:
    source = index(tmp_path / "source.db")
    original = read_candidates(source)[0]
    with sqlite3.connect(source) as db:
        db.execute(
            "UPDATE files SET modified='2026-10-11T00:00:00Z' WHERE id=?", (original.drive_id,)
        )
    assert read_candidates(source)[0].index_revision != original.index_revision
    output = tmp_path / "proposals-v1.json"
    assert write_review_package(source, output) == 3
    data = json.loads(output.read_text())
    assert data["canonical"] is False and data["provider_calls"] == 0
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_review_package(source, output)


def test_unsupported_exports_and_duplicate_drive_identities_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exported read-only"):
        read_candidates(tmp_path / "missing.db")
    invalid = tmp_path / "invalid.db"
    with sqlite3.connect(invalid):
        pass
    with pytest.raises(ValueError, match="schema"):
        read_candidates(invalid)
    source = index(tmp_path / "source.db")
    with sqlite3.connect(source) as db:
        db.execute("INSERT INTO files SELECT * FROM files WHERE mime='audio/mpeg'")
    with pytest.raises(ValueError, match="duplicate Drive"):
        read_candidates(source)
