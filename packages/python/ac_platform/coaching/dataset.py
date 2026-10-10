"""Read-only, reviewed placeholder topic exports; never synthesize or copy media.

The fixed local handoff is optional. Missing/malformed/unreviewed topics preserve
text lessons. Root/Strike F supplies exact transcript, human tag reviews and
verified narration receipts. Raw script tags and estimated timings are not
accepted as playback authority. No JSON/file path is returned to the browser.
"""

import hashlib
import os
from collections.abc import Generator
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from ac_platform.coaching.contracts import ClipSuggestion, GapType, Model, Slide
from ac_platform.coaching.media import (
    MediaTranscript,
    ReviewedClip,
    SegmentProposal,
    SegmentReview,
    reviewed_clip,
    select_clips,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash

DATASET_ROOT = Path("/home/acdev/datasets/synthetic-v1/coaching-media")
TOPIC_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,99}$"
SHA_PATTERN = r"^[0-9a-f]{64}$"
MAX_AUDIO_BYTES = 20 * 1024 * 1024


class Narration(Model):
    # Relative to this handoff root; no external URLs, provider fetch or traversal.
    relative_path: str = Field(pattern=r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+\.mp3$")
    source_sha256: str = Field(pattern=SHA_PATTERN)
    source_bytes: int = Field(gt=0, le=MAX_AUDIO_BYTES, strict=True)
    duration_ms: int = Field(gt=0, strict=True)
    verification: Literal["pending", "failed", "verified"]
    verification_reference: str = Field(min_length=1, max_length=256)


class PresentationReview(Model):
    subject_sha256: str = Field(pattern=SHA_PATTERN)
    decision: Literal["approve", "reject"]
    reviewer_reference: str = Field(min_length=1, max_length=256)
    reviewed_at: AwareDatetime


def presentation_subject(topic: "DatasetTopic") -> str:
    return content_hash(topic.model_dump(mode="json", exclude={"presentation_review"}))


class DatasetTopic(Model):
    schema_id: Literal["ac.sales-xray.coaching-dataset-topic/1"] = Field(
        default="ac.sales-xray.coaching-dataset-topic/1", alias="schema"
    )
    topic_id: str = Field(pattern=TOPIC_PATTERN)
    placeholder: Literal[True]
    voice: Literal["neutral"]
    transcript: MediaTranscript
    proposals: tuple[SegmentProposal, ...] = Field(max_length=100)
    # Exactly the current review per proposal. Historical reviews are retained
    # by the exporter; they must not authorize a superseded approval here.
    current_reviews: tuple[SegmentReview, ...] = Field(max_length=100)
    narration: Narration
    slides: tuple[Slide, ...] = Field(default=(), max_length=100)
    # Bind authored slides and narration verification as well as the existing
    # transcript/tag reviews. Changed slide text cannot reuse an approval.
    presentation_review: PresentationReview | None = None

    @model_validator(mode="after")
    def exact_topic(self) -> "DatasetTopic":
        source = self.transcript.source
        if (
            source.origin != "dataset"
            or source.source_id != self.topic_id
            or not source.placeholder
            or source.voice != "neutral"
            or source.source_sha256 != self.narration.source_sha256
            or source.duration_ms != self.narration.duration_ms
            or len({p.proposal_id for p in self.proposals}) != len(self.proposals)
            or len({r.proposal_id for r in self.current_reviews}) != len(self.current_reviews)
            or any(
                r.proposal_id not in {p.proposal_id for p in self.proposals}
                for r in self.current_reviews
            )
            or len({s.segment_id for s in self.slides}) != len(self.slides)
            or any(
                s.segment_id not in {s.segment_id for s in self.transcript.spans}
                for s in self.slides
            )
        ):
            raise ValueError("Topic, narration, source and slides must preserve exact identities.")
        return self

    def clips(self) -> tuple[ReviewedClip, ...]:
        if (
            self.narration.verification != "verified"
            or self.presentation_review is None
            or self.presentation_review.decision != "approve"
        ):
            return ()
        if self.presentation_review.subject_sha256 != presentation_subject(self) or any(
            self.presentation_review.reviewed_at < review.reviewed_at
            for review in self.current_reviews
        ):
            raise ValueError("Presentation review must bind the exact current topic export.")
        reviews = {r.proposal_id: r for r in self.current_reviews}
        clips = []
        for proposal in self.proposals:
            review = reviews.get(proposal.proposal_id)
            if review is None:
                continue
            clip = reviewed_clip(self.transcript, proposal, review)
            if clip:
                clips.append(clip)
        return tuple(clips)


def narration_path(root: Path, topic: DatasetTopic) -> Path | None:
    try:
        base = root.resolve(strict=True)
        path = (base / topic.narration.relative_path).resolve(strict=True)
        if not path.is_relative_to(base) or not path.is_file():
            return None
        if path.stat().st_size != topic.narration.source_bytes:
            return None
        return path
    except OSError:
        return None


def verified_narration(root: Path, topic: DatasetTopic) -> Generator[bytes]:
    """Hash and stream the same open descriptor, even if an export is replaced."""
    path = narration_path(root, topic)
    if path is None or topic.narration.verification != "verified":
        raise ValueError("Narration is unavailable.")
    with path.open("rb") as file:
        if os.fstat(file.fileno()).st_size != topic.narration.source_bytes:
            raise ValueError("Narration size does not match its verified revision.")
        if hashlib.file_digest(file, "sha256").hexdigest() != topic.narration.source_sha256:
            raise ValueError("Narration does not match its verified revision.")
        file.seek(0)
        while block := file.read(64 * 1024):
            yield block


def _revision(file: Path) -> tuple[int, int, int, int, int]:
    stat = file.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@lru_cache(maxsize=100)
def _read_topic(file: Path, revision: tuple[int, int, int, int, int]) -> DatasetTopic:
    topic = DatasetTopic.model_validate_json(file.read_bytes())
    if _revision(file) != revision:
        raise ValueError("Topic export changed during the read.")
    topic.clips()
    return topic


def read_topics(root: Path = DATASET_ROOT) -> tuple[DatasetTopic, ...]:
    """Bounded local export read; a bad topic cannot crash account Coaching."""
    topics = []
    try:
        files = sorted(root.glob("*.json"))[:100]
        for file in files:
            try:
                revision = _revision(file)
                if file.is_symlink() or revision[2] > 512 * 1024:
                    continue
                topic = _read_topic(file, revision)
                if file.name != f"{topic.topic_id}.json" or narration_path(root, topic) is None:
                    continue
                topics.append(topic)
            except (OSError, ValueError):
                continue
    except OSError:
        return ()
    return tuple(topics)


def suggestions(
    topics: tuple[DatasetTopic, ...], *, skill_id: str, gap_type: GapType
) -> tuple[ClipSuggestion, ...]:
    clips = tuple(clip for topic in topics for clip in topic.clips())
    chosen = select_clips(clips, skill_id=skill_id, gap_type=gap_type)
    by_source = {topic.transcript.source.key: topic for topic in topics}
    return tuple(
        ClipSuggestion(
            topic_id=by_source[clip.source.key].topic_id,
            revision=clip.transcript.sha256,
            review_id=clip.review.review_id,
            title=clip.source.title,
            kind=clip.source.kind,
            start_ms=clip.start_ms,
            end_ms=clip.end_ms,
            reason=clip.review.reason,
            takeaways=clip.review.takeaways,
            transcript_excerpt=clip.transcript_excerpt,
            slides=tuple(
                slide
                for slide in by_source[clip.source.key].slides
                if slide.segment_id in clip.proposal.segment_ids
            ),
        )
        for clip in chosen
    )
