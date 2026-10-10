"""Fictional local exports: no provider/content downloads or real teaching media."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ac_platform.coaching.dataset import (
    DatasetTopic,
    Narration,
    PresentationReview,
    Slide,
    narration_path,
    presentation_subject,
    read_topics,
    suggestions,
    verified_narration,
)
from tests.unit.coaching.test_media import media

AUDIO = b"fictional narration bytes, not playable media"


def topic(root: Path) -> DatasetTopic:
    transcript, proposal, review = media()
    source = transcript.source.model_copy(
        update={
            "origin": "dataset",
            "source_id": "fictional-impact",
            "source_sha256": hashlib.sha256(AUDIO).hexdigest(),
            "placeholder": True,
            "voice": "neutral",
            "kind": "video",
        }
    )
    transcript = transcript.model_copy(update={"source": source})
    proposal = proposal.model_copy(
        update={
            "source_key": source.key,
            "transcript_sha256": transcript.sha256,
        }
    )
    review = review.model_copy(update={"proposal_sha256": proposal.sha256})
    record = DatasetTopic(
        topic_id=source.source_id,
        placeholder=True,
        voice="neutral",
        transcript=transcript,
        proposals=(proposal,),
        current_reviews=(review,),
        narration=Narration(
            relative_path="audio/fictional-impact.mp3",
            source_sha256=source.source_sha256,
            source_bytes=len(AUDIO),
            duration_ms=source.duration_ms,
            verification="verified",
            verification_reference="fictional-exact-timing-review",
        ),
        slides=(Slide(segment_id="a", title="Fictional slide", bullets=("Check the impact.",)),),
    )
    record = record.model_copy(
        update={
            "presentation_review": PresentationReview(
                subject_sha256=presentation_subject(record),
                decision="approve",
                reviewer_reference="fictional-human-presentation-review",
                reviewed_at=review.reviewed_at,
            )
        }
    )
    (root / "audio").mkdir(exist_ok=True)
    (root / record.narration.relative_path).write_bytes(AUDIO)
    (root / f"{record.topic_id}.json").write_text(record.model_dump_json(by_alias=True))
    return record


def test_missing_dataset_keeps_text_fallback_and_import_preserves_topic_identity(tmp_path: Path):
    assert read_topics(tmp_path / "absent") == ()
    record = topic(tmp_path)
    loaded = read_topics(tmp_path)
    assert loaded == (record,)
    clips = suggestions(loaded, skill_id="problem_impact_desire", gap_type="judgment")
    assert len(clips) == 1
    clip = clips[0]
    assert clip.topic_id == record.topic_id and clip.revision == record.transcript.sha256
    assert clip.placeholder and clip.voice == "neutral" and clip.access == "full"
    assert (clip.start_ms, clip.end_ms) == (1000, 5000)
    assert clip.slides == record.slides and clip.reason == record.current_reviews[0].reason
    assert b"".join(verified_narration(tmp_path, record)) == AUDIO
    assert "relative_path" not in clip.model_dump() and "url" not in clip.model_dump()
    assert suggestions(loaded, skill_id="report_next_step", gap_type="uncertain") == ()


@pytest.mark.parametrize("state", ["pending", "failed"])
def test_unverified_audio_never_becomes_a_recommendation(tmp_path: Path, state: str):
    record = topic(tmp_path)
    raw = json.loads(record.model_dump_json(by_alias=True))
    raw["narration"]["verification"] = state
    (tmp_path / f"{record.topic_id}.json").write_text(json.dumps(raw))
    assert (
        suggestions(read_topics(tmp_path), skill_id="problem_impact_desire", gap_type="judgment")
        == ()
    )


@pytest.mark.parametrize(
    "change",
    ["review", "tags", "quality", "topic", "voice", "slides", "slide_text", "presentation", "path"],
)
def test_changed_reviews_or_unsafe_source_cannot_reach_coaching(tmp_path: Path, change: str):
    record = topic(tmp_path)
    raw = json.loads(record.model_dump_json(by_alias=True))
    if change == "review":
        raw["current_reviews"][0]["decision"] = "reject"
    elif change == "tags":
        raw["proposals"][0]["skill_ids"] = ["qualification"]
    elif change == "quality":
        raw["transcript"]["quality"] = "needs_review"
    elif change == "topic":
        raw["topic_id"] = "other-topic"
    elif change == "voice":
        raw["transcript"]["source"]["voice"] = None
    elif change == "slides":
        raw["slides"][0]["segment_id"] = "absent"
    elif change == "slide_text":
        raw["slides"][0]["bullets"] = ["Changed lesson direction."]
    elif change == "presentation":
        raw["presentation_review"] = None
    else:
        raw["narration"]["relative_path"] = "../other.mp3"
    (tmp_path / f"{record.topic_id}.json").write_text(json.dumps(raw))
    assert (
        suggestions(read_topics(tmp_path), skill_id="problem_impact_desire", gap_type="uncertain")
        == ()
    )


def test_missing_bad_json_and_symlink_do_not_crash_other_topics(tmp_path: Path):
    record = topic(tmp_path)
    (tmp_path / "broken.json").write_text("{bad")
    (tmp_path / "link.json").symlink_to(tmp_path / f"{record.topic_id}.json")
    assert read_topics(tmp_path) == (record,)
    audio = tmp_path / record.narration.relative_path
    audio.unlink()
    assert read_topics(tmp_path) == ()
    other = tmp_path.parent / "outside-placeholder.mp3"
    other.write_bytes(AUDIO)
    audio.symlink_to(other)
    assert narration_path(tmp_path, record) is None


def test_replaced_bytes_never_stream_under_previous_review(tmp_path: Path):
    record = topic(tmp_path)
    path = tmp_path / record.narration.relative_path
    path.write_bytes(b"x" * len(AUDIO))
    with pytest.raises(ValueError, match="verified revision"):
        next(verified_narration(tmp_path, record))


def test_stream_keeps_the_verified_descriptor_if_export_path_is_replaced(tmp_path: Path):
    record = topic(tmp_path)
    iterator = verified_narration(tmp_path, record)
    first = next(iterator)
    path = tmp_path / record.narration.relative_path
    path.rename(path.with_suffix(".old"))
    path.write_bytes(b"x" * len(AUDIO))
    assert first + b"".join(iterator) == AUDIO


def test_dataset_sources_must_remain_labelled_neutral_placeholders(tmp_path: Path):
    record = topic(tmp_path)
    raw = record.model_dump(by_alias=True)
    raw["placeholder"] = False
    with pytest.raises(ValidationError):
        DatasetTopic.model_validate(raw)


def test_full_115_topic_library_does_not_hide_the_last_reviewed_topic(tmp_path: Path):
    record = topic(tmp_path)
    for number in range(115):
        (tmp_path / f"_draft-{number:03}.json").write_text("{}")
    assert read_topics(tmp_path) == (record,)
