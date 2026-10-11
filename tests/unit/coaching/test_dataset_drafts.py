"""Fictional exact-manifest drafts remain pending, estimated and unplayable."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from ac_platform.coaching.dataset_drafts import import_drafts, main


def draft(root: Path) -> tuple[Path, Path, dict[str, Any]]:
    root.mkdir(exist_ok=True)
    scripts = root / "scripts"
    scripts.mkdir()
    source = scripts / "fictional.docx"
    source.write_bytes(b"fictional source document")
    index = {
        "schema_version": "coaching-media/1",
        "synthetic": True,
        "placeholder": True,
        "voice": "neutral",
        "topics": [{"id": "fictional-topic"}],
        "source_documents": [
            {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        ],
    }
    (root / "index.json").write_text(json.dumps(index))
    record = {
        "schema_version": "coaching-media/1",
        "synthetic": True,
        "placeholder": True,
        "voice": "neutral",
        "id": "fictional-topic",
        "title": "Fictional draft",
        "kind": "audio",
        "skill": "skill-2",
        "gap_type": "skill_execution",
        "script_origin": "provided_docx",
        "source_docx": str(source),
        "script_text": "An invented script for testing.",
        "editorial_review": "approved",  # raw text is never review authority
        "segments": [
            {
                "id": "fictional-segment",
                "topic_id": "fictional-topic",
                "skill": "skill-7",
                "gap_type": "skill_execution",
                "placeholder": True,
                "voice": "neutral",
                "playable": False,
                "timing_source": "estimated",
                "estimated_duration_ms": 30_000,
                "text": "One invented teaching idea.",
            }
        ],
    }
    path = root / "fictional-topic.json"
    path.write_text(json.dumps(record))
    return scripts, path, record


def test_preserves_exact_manifest_id_hashes_and_unmapped_proposals(tmp_path: Path):
    scripts, path, _ = draft(tmp_path)
    batch = import_drafts(tmp_path, scripts)
    assert len(batch.proposals) == 1 and batch.rejected_records == 0
    proposal = batch.proposals[0]
    assert proposal.topic_id == "fictional-topic"
    assert proposal.export_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert proposal.source_document_sha256 and proposal.script_sha256
    assert proposal.draft_skill == "skill-2" and proposal.segments[0].draft_skill == "skill-7"
    assert proposal.draft_gap_type == "skill_execution"
    assert proposal.canonical_skill_id is None and proposal.canonical_gap_type is None
    assert proposal.review_state == "pending_review" and proposal.playback_state == "unavailable"
    assert not proposal.segments[0].playable and not batch.queue_is_canonical
    assert "text" not in proposal.segments[0].model_dump()


@pytest.mark.parametrize(
    "change", ["source", "id", "path", "voice", "playable", "timing", "duplicate"]
)
def test_unverified_sources_or_claimed_playback_are_rejected(tmp_path: Path, change: str):
    scripts, path, record = draft(tmp_path)
    if change == "source":
        (scripts / "fictional.docx").write_bytes(b"changed source")
    elif change == "id":
        record["id"] = "other"
    elif change == "path":
        index = json.loads((tmp_path / "index.json").read_text())
        index["topics"] = [{"id": "../outside"}]
        (tmp_path / "index.json").write_text(json.dumps(index))
    elif change == "voice":
        record["voice"] = "dipak"
    elif change == "playable":
        record["segments"][0]["playable"] = True
    elif change == "timing":
        record["segments"][0]["timing_source"] = "verified"
    else:
        record["segments"].append(record["segments"][0])
    path.write_text(json.dumps(record))
    batch = import_drafts(tmp_path, scripts)
    assert batch.proposals == () and batch.rejected_records == 1


def test_authored_and_title_only_origins_are_not_relabelled_supplied_scripts(tmp_path: Path):
    scripts, path, record = draft(tmp_path)
    for origin in ["locally_authored_placeholder", "roadmap_title_only"]:
        record["script_origin"] = origin
        if origin == "roadmap_title_only":
            record["script_text"], record["segments"] = "", []
        path.write_text(json.dumps(record))
        proposal = import_drafts(tmp_path, scripts).proposals[0]
        assert proposal.script_origin == origin and proposal.review_state == "pending_review"
        if origin == "roadmap_title_only":
            assert proposal.script_sha256 is None and proposal.segments == ()


def test_cli_snapshot_is_immutable_idempotent_and_counts_only(
    tmp_path: Path, monkeypatch: Any, capsys: Any
):
    scripts, path, record = draft(tmp_path)
    original = import_drafts
    monkeypatch.setattr(
        "ac_platform.coaching.dataset_drafts.import_drafts", lambda root: original(root, scripts)
    )
    output = tmp_path / "receipts"
    output.mkdir()
    monkeypatch.setattr(
        "sys.argv", ["drafts", "--root", str(tmp_path), "--output-dir", str(output)]
    )
    main()
    first = next(output.glob("*.json"))
    before = first.read_bytes()
    main()
    assert len(list(output.glob("*.json"))) == 1 and first.read_bytes() == before
    record["script_text"] = "Changed draft needs a new review."
    path.write_text(json.dumps(record))
    main()
    assert len(list(output.glob("*.json"))) == 2 and first.read_bytes() == before
    assert "An invented script" not in capsys.readouterr().out
    assert first.stat().st_mode & 0o777 == 0o600
