"""Timestamped, revision-bound media proposals and reviewed clip selection.

These immutable contracts contain text and source references, never media bytes.
They do not activate a provider, persist an approval, grant an entitlement or
authorize streaming. Runtime use requires canonical review/allowance records and
an authorized source resolver; until then Coaching retains its text lesson.
"""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from ac_platform.coaching.catalogue import Category
from ac_platform.coaching.contracts import GapType, Model
from ac_platform.coaching.report_adapter import SKILLS
from ac_platform.conversation_intelligence.checkpoints import content_hash


class MediaSource(Model):
    origin: Literal["drive", "owner_upload"]
    source_id: str = Field(min_length=1, max_length=200)
    source_revision: str = Field(min_length=1, max_length=256)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=256)
    category: Category
    kind: Literal["audio", "video"]
    duration_ms: int = Field(gt=0, strict=True)
    # References to actual review/rights records, not proof inferred from a name.
    dipak_provenance_reference: str = Field(min_length=1, max_length=256)
    permission_reference: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def stable_identity(self) -> "MediaSource":
        if self.origin == "drive":
            if re.fullmatch(r"[A-Za-z0-9_-]{10,200}", self.source_id) is None:
                raise ValueError("Media needs an exact Drive identity.")
        else:
            UUID(self.source_id)
        return self

    @property
    def key(self) -> str:
        return f"{self.origin}:{self.source_id}"


class TranscriptSpan(Model):
    segment_id: str = Field(min_length=1, max_length=128)
    start_ms: int = Field(ge=0, strict=True)
    end_ms: int = Field(gt=0, strict=True)
    text: str = Field(min_length=1, max_length=8000)

    @model_validator(mode="after")
    def ordered(self) -> "TranscriptSpan":
        if self.end_ms <= self.start_ms or not self.text.strip():
            raise ValueError("A transcript span needs real text and ordered timestamps.")
        return self


class MediaTranscript(Model):
    source: MediaSource
    transcript_revision: str = Field(min_length=1, max_length=256)
    languages: tuple[Literal["hi", "mr", "en"], ...] = Field(min_length=1, max_length=3)
    spans: tuple[TranscriptSpan, ...] = Field(min_length=1)
    provider_route_reference: str = Field(min_length=1, max_length=256)
    provider_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    activation_approval_reference: str = Field(min_length=1, max_length=256)
    cost_receipt_reference: str = Field(min_length=1, max_length=256)
    quality: Literal["needs_review", "reviewed"] = "needs_review"
    quality_review_reference: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def source_alignment(self) -> "MediaTranscript":
        if len({span.segment_id for span in self.spans}) != len(self.spans):
            raise ValueError("Transcript segment identities must be unique.")
        if any(span.end_ms > self.source.duration_ms for span in self.spans) or any(
            right.start_ms < left.start_ms
            for left, right in zip(self.spans, self.spans[1:], strict=False)
        ):
            raise ValueError("Transcript timestamps must follow the source duration and order.")
        if self.quality == "reviewed" and self.quality_review_reference is None:
            raise ValueError("Reviewed transcript quality needs an attributable review.")
        return self

    @property
    def sha256(self) -> str:
        # Bind the source, route/cost provenance and exact timestamped text.
        return content_hash(self.model_dump(mode="json"))


class SegmentProposal(Model):
    proposal_id: UUID
    source_key: str
    source_revision: str
    transcript_revision: str
    transcript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    segment_ids: tuple[str, ...] = Field(min_length=1)
    skill_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    topics: tuple[str, ...] = Field(min_length=1, max_length=12)
    gap_types: tuple[GapType, ...] = Field(min_length=1, max_length=11)
    rationale: str = Field(min_length=1, max_length=2000)
    proposal_reference: str = Field(min_length=1, max_length=256)
    created_at: datetime
    status: Literal["pending_review"] = "pending_review"

    @model_validator(mode="after")
    def supported_tags(self) -> "SegmentProposal":
        if not set(self.skill_ids) <= SKILLS or any(not topic.strip() for topic in self.topics):
            raise ValueError("Clip tags must name supported skills and nonblank topics.")
        if len(set(self.segment_ids)) != len(self.segment_ids):
            raise ValueError("A clip cannot repeat transcript segments.")
        return self

    @property
    def sha256(self) -> str:
        return content_hash(self.model_dump(mode="json"))


class SegmentReview(Model):
    review_id: UUID
    proposal_id: UUID
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approve", "reject"]
    reviewer_reference: str = Field(min_length=1, max_length=256)
    reviewed_at: datetime
    reason: str = Field(min_length=1, max_length=2000)
    takeaways: tuple[str, ...] = Field(min_length=1, max_length=5)
    # A later review supersedes an earlier decision; never mutate its history.
    supersedes_review_id: UUID | None = None


class ReviewedClip(Model):
    source: MediaSource
    transcript: MediaTranscript
    proposal: SegmentProposal
    review: SegmentReview
    start_ms: int
    end_ms: int
    transcript_excerpt: str

    @model_validator(mode="after")
    def approved_exact_content(self) -> "ReviewedClip":
        spans = _reviewed_spans(self.transcript, self.proposal, self.review)
        if (
            not spans
            or self.source != self.transcript.source
            or self.start_ms != spans[0].start_ms
            or self.end_ms != max(span.end_ms for span in spans)
            or self.transcript_excerpt != "\n".join(span.text for span in spans)
        ):
            raise ValueError("A reviewed clip must preserve its exact approved source spans.")
        return self


def _reviewed_spans(
    transcript: MediaTranscript, proposal: SegmentProposal, review: SegmentReview
) -> tuple[TranscriptSpan, ...]:
    if (
        proposal.source_key != transcript.source.key
        or proposal.source_revision != transcript.source.source_revision
        or proposal.transcript_revision != transcript.transcript_revision
        or proposal.transcript_sha256 != transcript.sha256
        or review.proposal_id != proposal.proposal_id
        or review.proposal_sha256 != proposal.sha256
        or review.reviewed_at < proposal.created_at
    ):
        raise ValueError("Review must bind the exact proposal, source and transcript revision.")
    if review.decision != "approve" or transcript.quality != "reviewed":
        return ()
    positions = [
        index
        for index, span in enumerate(transcript.spans)
        if span.segment_id in proposal.segment_ids
    ]
    if len(positions) != len(proposal.segment_ids) or positions != list(
        range(positions[0], positions[-1] + 1)
    ):
        raise ValueError("A clip must contain a contiguous selection of existing source spans.")
    spans = tuple(transcript.spans[index] for index in positions)
    if any(right.start_ms < left.end_ms for left, right in zip(spans, spans[1:], strict=False)):
        raise ValueError("Overlapping speaker spans need alignment review before making a clip.")
    return spans


def reviewed_clip(
    transcript: MediaTranscript, proposal: SegmentProposal, review: SegmentReview
) -> ReviewedClip | None:
    spans = _reviewed_spans(transcript, proposal, review)
    if not spans:
        return None
    return ReviewedClip(
        source=transcript.source,
        transcript=transcript,
        proposal=proposal,
        review=review,
        start_ms=spans[0].start_ms,
        end_ms=max(span.end_ms for span in spans),
        transcript_excerpt="\n".join(span.text for span in spans),
    )


def select_clips(
    clips: tuple[ReviewedClip, ...],
    *,
    skill_id: str,
    gap_type: GapType,
    topic: str | None = None,
    maximum: int = 3,
) -> tuple[ReviewedClip, ...]:
    """Exact relevant reviewed segments only; an empty result keeps the text lesson.

    No inferred learner format preference or filename/prose-based skill match.
    Callers must supply the current canonical reviews; superseded approvals do
    not authorize playback even if an earlier in-memory clip still exists.
    """
    if type(maximum) is not int or not 1 <= maximum <= 3:
        raise ValueError("Recommend one to three clips.")
    eligible = []
    for clip in clips:
        # Revalidate even model_copy/construct inputs at this product boundary.
        clip = ReviewedClip.model_validate_json(clip.model_dump_json())
        tags = clip.proposal
        if (
            skill_id in tags.skill_ids
            and (gap_type == "uncertain" or gap_type in tags.gap_types)
            and (topic is None or topic in tags.topics)
        ):
            eligible.append(clip)
    eligible.sort(
        key=lambda clip: (
            len(clip.proposal.skill_ids),
            len(clip.proposal.gap_types),
            clip.source.kind != "audio",
            clip.source.key,
            clip.start_ms,
        )
    )
    selected: list[ReviewedClip] = []
    for clip in eligible:
        if any(
            clip.source.key == prior.source.key
            and clip.start_ms < prior.end_ms
            and prior.start_ms < clip.end_ms
            for prior in selected
        ):
            continue
        selected.append(clip)
        if len(selected) == maximum:
            break
    return tuple(selected)


class PreviewAllowance(Model):
    """Already resolved entitlements/credits policy; no plan-name/payment lookup."""

    policy_revision: str = Field(min_length=1, max_length=256)
    full_access: bool
    preview_ms: int | None = Field(default=None, ge=0, strict=True)
    clip_limit: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def explicit_limit(self) -> "PreviewAllowance":
        if not self.full_access and self.preview_ms is None and self.clip_limit is None:
            raise ValueError("Limited access needs an explicit preview allowance.")
        return self


class PreviewUsage(Model):
    # These counts must come from durable usage state, not client telemetry.
    usage_revision: str = Field(min_length=1, max_length=256)
    played_ms: int = Field(ge=0, strict=True)
    clips_started: int = Field(ge=0, strict=True)


class PlaybackWindow(Model):
    state: Literal["full", "preview", "locked"]
    start_ms: int
    end_ms: int | None
    policy_revision: str
    usage_revision: str
    action_label: str | None = None


def playback_window(
    clip: ReviewedClip, allowance: PreviewAllowance, usage: PreviewUsage
) -> PlaybackWindow:
    """Plan a server-enforced window; never grant access through a client player.

    The eventual streaming boundary must reserve/read durable usage and enforce
    this window on every request. This pure function does not consume allowance.
    Internal/free/unlimited open access is represented by full_access=True from
    the Coaching entitlement, never by a payment-provider status.
    """
    clip = ReviewedClip.model_validate_json(clip.model_dump_json())
    common = dict(
        start_ms=clip.start_ms,
        policy_revision=allowance.policy_revision,
        usage_revision=usage.usage_revision,
    )
    if allowance.full_access:
        return PlaybackWindow(**common, state="full", end_ms=clip.end_ms)
    remaining = (
        clip.end_ms - clip.start_ms
        if allowance.preview_ms is None
        else max(0, allowance.preview_ms - usage.played_ms)
    )
    locked = remaining == 0 or (
        allowance.clip_limit is not None and usage.clips_started >= allowance.clip_limit
    )
    return PlaybackWindow(
        **common,
        state="locked" if locked else "preview",
        end_ms=None if locked else min(clip.end_ms, clip.start_ms + remaining),
        action_label="Get the full coaching",
    )
