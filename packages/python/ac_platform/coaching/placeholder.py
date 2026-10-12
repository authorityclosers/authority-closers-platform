"""Packaged placeholder narration as Dipak's clips (owner, 11 Oct 2026 14:15 IST).

Strike F's verified neutral-voice narrations of Dipak's scripts, one manifest
per release (`scripts/coaching_placeholder_media.py`). Each skill's
top-priority topic plays in full; its other topics play a 15-second free
preview and then lead to the full coaching and the Learner's Academy. A locked
topic ships only its preview cut, a separate file, so the rest cannot be
fetched by any URL; one without a cut stays locked. Narration is a labelled
placeholder and never imitates Dipak.
"""

import hashlib
import json
import os
from collections.abc import Generator
from functools import cache
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid5

from pydantic import Field, ValidationError

from ac_platform.coaching.contracts import (
    AcademyLink,
    ClipOffer,
    ClipSuggestion,
    GapType,
    Model,
    Slide,
)

MEDIA = Path(__file__).with_name("placeholder_media")
OPEN = "AUT-1678-open-access"
LOCKED = "AUT-1678-demo-one-free-topic-per-skill"
OFFER = ClipOffer(
    full_coaching_href="/plans",
    academy=AcademyLink(
        href="https://learner.authorityclosers.com/",
        label="Dipak's courses on the Learner's Academy",
    ),
)
# Stable identity for the owner's 11 Oct approval of these placeholders.
APPROVAL = UUID("4f7d3c1e-9a2b-5c6d-8e7f-11a0c0a1d678")
SKILL_LABELS = {
    "human_connection_trust": "Human Connection & Trust",
    "discovery_deep_understanding": "Discovery & Deep Understanding",
    "qualification": "Qualification",
    "problem_impact_desire": "Problem, Impact & Desire Clarity",
    "solution_relevance_presentation": "Solution Relevance & Presentation",
    "certainty_objection_intelligence": "Certainty & Objection Intelligence",
    "closing_decision_management": "Closing & Decision Management",
    "communication_tonality": "Communication & Tonality",
}


class PlaceholderTopic(Model):
    topic_id: str = Field(pattern=r"^syn-coach-[a-z]+-[0-9]{3}$")
    title: str = Field(min_length=1, max_length=256)
    kind: Literal["audio", "video"]
    skill_id: str
    gap_type: GapType
    topic_tag: str = ""
    priority: int
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    narration: str = Field(min_length=1)
    slides: tuple[Slide, ...] = ()
    takeaways: tuple[str, ...] = Field(min_length=1)
    audio_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_bytes: int = Field(gt=0)
    free: bool
    # A locked topic's free preview: its own cut file and real length.
    preview_ms: int | None = Field(default=None, gt=0)
    preview_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    preview_bytes: int | None = Field(default=None, gt=0)

    @property
    def previewable(self) -> bool:
        # The cut is always the file's first seconds, so the clip must start at 0.
        return (
            not self.free
            and self.start_ms == 0
            and self.preview_ms is not None
            and self.preview_sha256 is not None
            and self.preview_bytes is not None
            and self.start_ms + self.preview_ms < self.end_ms
        )

    @property
    def review_id(self) -> UUID:
        return uuid5(APPROVAL, f"{self.topic_id}:{self.audio_sha256}")


@cache
def topics(root: Path = MEDIA) -> tuple[PlaceholderTopic, ...]:
    """The packaged manifest; a missing or malformed one means no clips."""
    try:
        data = json.loads((root / "manifest.json").read_text())
    except (OSError, ValueError):
        return ()
    if not isinstance(data, dict) or not isinstance(data.get("topics"), list):
        return ()
    parsed = []
    for raw in data["topics"]:
        try:
            topic = PlaceholderTopic.model_validate(raw)
        except ValidationError:
            continue
        if topic.skill_id in SKILL_LABELS and topic.end_ms > topic.start_ms:
            parsed.append(topic)
    return tuple(parsed)


GAP_WORDS = {
    "knowledge": "knowing what to ask",
    "judgment": "spotting the moment live",
    "execution": "saying it smoothly",
    "habit_recall": "remembering it live",
    "confidence": "asking without holding back",
}


def _clip(
    topic: PlaceholderTopic, gap_type: str | None = None, *, their: bool = False
) -> ClipSuggestion:
    label = SKILL_LABELS[topic.skill_id]
    # Say why only with facts on both sides: the lesson's tag and this coaching's
    # likely reason. A guessed match is never claimed.
    gap = (
        f" It helps with {GAP_WORDS[topic.gap_type]}, the likely reason here."
        if gap_type == topic.gap_type and topic.gap_type in GAP_WORDS
        else ""
    )
    who = "they’re" if their else "you’re"
    preview_end = (
        topic.start_ms + topic.preview_ms
        if topic.previewable and topic.preview_ms is not None
        else None
    )
    free_part = (
        f" The first {round((preview_end - topic.start_ms) / 1000)} seconds are free."
        if preview_end is not None
        else ""
    )
    return ClipSuggestion(
        topic_id=topic.topic_id,
        revision=topic.audio_sha256,
        review_id=topic.review_id,
        title=topic.title,
        kind=topic.kind,
        access="full" if topic.free else "preview" if preview_end is not None else "locked",
        preview_end_ms=preview_end,
        entitlement_policy=OPEN if topic.free else LOCKED,
        start_ms=topic.start_ms,
        end_ms=topic.end_ms,
        reason=(
            f"Dipak’s lesson on {label}, the skill {who} working on.{gap}"
            if topic.free
            else f"Another lesson on {label}, from Dipak’s full coaching.{free_part}{gap}"
        ),
        takeaways=topic.takeaways,
        transcript_excerpt=topic.narration,
        slides=topic.slides if topic.free else (),
        offer=None if topic.free else OFFER,
    )


def clips_for(
    skill_id: str, root: Path = MEDIA, *, gap_type: str | None = None, their: bool = False
) -> tuple[ClipSuggestion, ...]:
    """One free lesson and one locked lesson for an assessed skill; else none.

    Among the skill's further lessons, one tagged for the likely gap comes
    first (spec 11: the most specific asset). An unlinked report suggestion
    has no assessed skill, so no clip is guessed. `their`: another rep's
    coaching, so the reason says "they're", not "you're".
    """
    matching = sorted((t for t in topics(root) if t.skill_id == skill_id), key=lambda t: t.priority)
    free = next((t for t in matching if t.free), None)
    further = [t for t in matching if not t.free]
    locked = next((t for t in further if t.gap_type == gap_type), None) or next(iter(further), None)
    return tuple(_clip(t, gap_type, their=their) for t in (free, locked) if t is not None)


def playable(
    topic_id: str, revision: str, review_id: UUID, root: Path = MEDIA
) -> PlaceholderTopic | None:
    """A free or previewable topic matching the exact clip identity.

    A previewable topic plays only its preview cut (see `narration`); a locked
    topic without one never plays.
    """
    return next(
        (
            t
            for t in topics(root)
            if t.topic_id == topic_id
            and (t.free or t.previewable)
            and t.audio_sha256 == revision
            and t.review_id == review_id
        ),
        None,
    )


def audio_file(topic: PlaceholderTopic) -> tuple[str, int, str]:
    """(file name, bytes, sha256) of what this topic may stream: all or the preview."""
    if topic.free:
        return f"{topic.topic_id}.mp3", topic.audio_bytes, topic.audio_sha256
    if topic.previewable and topic.preview_bytes and topic.preview_sha256:
        return f"{topic.topic_id}.preview.mp3", topic.preview_bytes, topic.preview_sha256
    raise ValueError("Locked coaching has no playable narration.")


def narration(topic: PlaceholderTopic, root: Path = MEDIA) -> Generator[bytes]:
    """Hash and stream the same open file; a changed file is refused."""
    name, size, digest = audio_file(topic)
    with (root / name).open("rb") as file:
        if os.fstat(file.fileno()).st_size != size:
            raise ValueError("Narration size does not match its revision.")
        if hashlib.file_digest(file, "sha256").hexdigest() != digest:
            raise ValueError("Narration does not match its revision.")
        file.seek(0)
        while block := file.read(64 * 1024):
            yield block
