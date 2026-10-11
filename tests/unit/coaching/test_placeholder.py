"""Packaged placeholder narration: one free lesson per skill, locked ones never play."""

import json
import shutil
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from ac_platform.coaching import placeholder
from ac_platform.coaching.contracts import ClipSuggestion

SKILLS = tuple(placeholder.SKILL_LABELS)


def test_every_skill_has_one_free_lesson_and_a_locked_one_leads_to_the_academy() -> None:
    for skill in SKILLS:
        clips = placeholder.clips_for(skill)
        assert clips and clips[0].access == "full"
        assert clips[0].entitlement_policy == "AUT-1678-open-access"
        assert clips[0].offer is None and clips[0].slides
        for locked in clips[1:]:
            assert locked.access == "locked" and locked.slides == ()
            assert locked.offer is not None and locked.offer.full_coaching_href == "/plans"
            assert locked.offer.academy is not None
            assert locked.offer.academy.href.startswith("https://learner.authorityclosers.com/")
    assert placeholder.clips_for("report_next_step") == ()


def test_only_free_topics_ship_audio_and_play() -> None:
    topics = placeholder.topics()
    shipped = {path.stem for path in placeholder.MEDIA.glob("*.mp3")}
    assert shipped == {t.topic_id for t in topics if t.free}
    for topic in topics:
        found = placeholder.playable(topic.topic_id, topic.audio_sha256, topic.review_id)
        assert (found is not None) is topic.free
    free = next(t for t in topics if t.free)
    assert sum(len(block) for block in placeholder.narration(free)) == free.audio_bytes
    assert placeholder.playable(free.topic_id, "0" * 64, free.review_id) is None
    assert placeholder.playable(free.topic_id, free.audio_sha256, UUID(int=1)) is None


def test_a_changed_or_missing_file_is_refused_and_a_bad_manifest_means_no_clips(
    tmp_path: Path,
) -> None:
    free = next(t for t in placeholder.topics() if t.free)
    shutil.copy(placeholder.MEDIA / "manifest.json", tmp_path / "manifest.json")
    (tmp_path / f"{free.topic_id}.mp3").write_bytes(b"x" * free.audio_bytes)
    placeholder.topics.cache_clear()
    with pytest.raises(ValueError, match="does not match"):
        list(placeholder.narration(free, tmp_path))
    (tmp_path / "manifest.json").write_text(json.dumps({"topics": "broken"}))
    assert placeholder.topics(tmp_path) == ()
    assert placeholder.clips_for("qualification", tmp_path) == ()
    placeholder.topics.cache_clear()


def test_only_the_open_policy_grants_a_full_clip_and_a_lock_needs_an_offer() -> None:
    clip = placeholder.clips_for("qualification")[0].model_dump()
    with pytest.raises(ValidationError, match="open Coaching policy"):
        ClipSuggestion.model_validate(
            {**clip, "entitlement_policy": "AUT-1678-demo-one-free-topic-per-skill"}
        )
    with pytest.raises(ValidationError, match="lead to the full coaching"):
        ClipSuggestion.model_validate(
            {
                **clip,
                "access": "locked",
                "entitlement_policy": "AUT-1678-demo-one-free-topic-per-skill",
            }
        )
    with pytest.raises(ValidationError):
        ClipSuggestion.model_validate(
            {
                **clip,
                "access": "locked",
                "entitlement_policy": "AUT-1678-demo-one-free-topic-per-skill",
                "offer": {
                    "full_coaching_href": "https://pay.example.test/checkout",
                    "academy": None,
                },
            }
        )


def test_a_lesson_for_the_likely_gap_comes_first_and_says_so_only_when_true() -> None:
    execution = placeholder.clips_for("closing_decision_management", gap_type="execution")
    judgment = placeholder.clips_for("closing_decision_management", gap_type="judgment")
    assert execution[1].topic_id == "syn-coach-video-012"
    assert judgment[1].topic_id == "syn-coach-video-015"
    assert "execution gap" in execution[1].reason
    # The free lesson is tagged judgment: no claim when the gap differs.
    assert "gap" not in execution[0].reason
    assert "judgment gap" in judgment[0].reason
    unknown = placeholder.clips_for("closing_decision_management", gap_type="uncertain")
    assert all("gap" not in clip.reason for clip in unknown)
