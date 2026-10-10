"""Invented media only: approval binding, source timing, relevance and previews."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from ac_platform.coaching.media import (
    MediaSource,
    MediaTranscript,
    PreviewAllowance,
    PreviewUsage,
    SegmentProposal,
    SegmentReview,
    TranscriptSpan,
    playback_window,
    reviewed_clip,
    select_clips,
)

NOW = datetime(2026, 10, 10, tzinfo=UTC)


def media(index: int = 1):
    source = MediaSource(
        origin="drive",
        source_id=f"fictional_media_{index}",
        source_revision="fictional-source-v1",
        source_sha256=f"{index:064x}",
        title="Fictional lesson on consequence questions",
        category="Coach content",
        kind="audio",
        duration_ms=120_000,
        dipak_provenance_reference="fictional-creator-review",
        permission_reference="fictional-media-rights",
    )
    transcript = MediaTranscript(
        source=source,
        transcript_revision="fictional-transcript-v1",
        languages=("hi", "mr", "en"),
        spans=(
            TranscriptSpan(
                segment_id="a", start_ms=1000, end_ms=3000, text="Start with the problem."
            ),
            TranscriptSpan(
                segment_id="b", start_ms=3000, end_ms=5000, text="Understand its impact."
            ),
            TranscriptSpan(segment_id="c", start_ms=5000, end_ms=7000, text="Check the outcome."),
        ),
        provider_route_reference="fictional-existing-asr-route",
        provider_response_sha256="a" * 64,
        activation_approval_reference="fictional-provider-approval",
        cost_receipt_reference="fictional-cost-receipt",
        quality="reviewed",
        quality_review_reference="fictional-transcript-review",
    )
    proposal = SegmentProposal(
        proposal_id=UUID(int=index),
        source_key=source.key,
        source_revision=source.source_revision,
        transcript_revision=transcript.transcript_revision,
        transcript_sha256=transcript.sha256,
        segment_ids=("a", "b"),
        skill_ids=("problem_impact_desire",),
        topics=("consequence questions",),
        gap_types=("judgment",),
        rationale="This invented segment shows when to explore the consequence.",
        proposal_reference="fictional-subscription-handoff",
        created_at=NOW,
    )
    review = SegmentReview(
        review_id=UUID(int=100 + index),
        proposal_id=proposal.proposal_id,
        proposal_sha256=proposal.sha256,
        decision="approve",
        reviewer_reference="fictional-human-reviewer",
        reviewed_at=NOW,
        reason="The clip addresses the moment before a recommendation.",
        takeaways=("Check whether the consequence is already clear.",),
    )
    return transcript, proposal, review


def test_review_uses_exact_source_timestamps_and_real_transcript_text() -> None:
    transcript, proposal, review = media()
    clip = reviewed_clip(transcript, proposal, review)
    assert (clip.start_ms, clip.end_ms) == (1000, 5000)
    assert clip.transcript_excerpt == "Start with the problem.\nUnderstand its impact."
    assert clip.review.reason == review.reason
    assert proposal.status == "pending_review"
    assert "video_bytes" not in clip.model_dump()


def test_rejected_tags_or_unreviewed_transcript_never_reach_coaching() -> None:
    transcript, proposal, review = media()
    assert (
        reviewed_clip(transcript, proposal, review.model_copy(update={"decision": "reject"}))
        is None
    )
    unreviewed = transcript.model_copy(
        update={"quality": "needs_review", "quality_review_reference": None}
    )
    proposal = proposal.model_copy(update={"transcript_sha256": unreviewed.sha256})
    review = review.model_copy(update={"proposal_sha256": proposal.sha256})
    assert reviewed_clip(unreviewed, proposal, review) is None


@pytest.mark.parametrize("change", ["source", "text", "timing", "tags", "revision"])
def test_review_cannot_authorize_changed_source_text_timing_or_tags(change: str) -> None:
    transcript, proposal, review = media()
    if change == "source":
        transcript = transcript.model_copy(update={"source": media(2)[0].source})
    elif change in {"text", "timing"}:
        span = transcript.spans[0].model_copy(
            update={
                "text": "A changed lesson." if change == "text" else transcript.spans[0].text,
                "start_ms": 500 if change == "timing" else transcript.spans[0].start_ms,
            }
        )
        transcript = transcript.model_copy(update={"spans": (span, *transcript.spans[1:])})
    elif change == "tags":
        proposal = proposal.model_copy(update={"skill_ids": ("qualification",)})
    else:
        proposal = proposal.model_copy(update={"transcript_revision": "v2"})
    with pytest.raises(ValueError, match="exact proposal"):
        reviewed_clip(transcript, proposal, review)


@pytest.mark.parametrize("segments", [("a", "c"), ("missing",)])
def test_clips_cannot_invent_or_skip_source_segments(segments: tuple[str, ...]) -> None:
    transcript, proposal, review = media()
    proposal = proposal.model_copy(update={"segment_ids": segments})
    review = review.model_copy(update={"proposal_sha256": proposal.sha256})
    with pytest.raises(ValueError, match="contiguous"):
        reviewed_clip(transcript, proposal, review)


def test_invalid_timestamps_duration_or_claimed_quality_are_rejected() -> None:
    transcript, _, _ = media()
    with pytest.raises(ValidationError):
        TranscriptSpan(segment_id="x", start_ms=True, end_ms=3000, text="Example")
    with pytest.raises(ValidationError):
        MediaTranscript.model_validate(transcript.model_dump() | {"quality_review_reference": None})
    with pytest.raises(ValidationError):
        MediaTranscript.model_validate(
            transcript.model_dump()
            | {
                "spans": [
                    TranscriptSpan(segment_id="x", start_ms=119_000, end_ms=121_000, text="Example")
                ],
            }
        )


def test_selection_is_specific_bounded_and_explained_with_no_unrelated_filler() -> None:
    clips = tuple(reviewed_clip(*media(index)) for index in range(1, 6))
    selected = select_clips(clips, skill_id="problem_impact_desire", gap_type="judgment")
    assert len(selected) == 3
    assert all(clip.review.reason and clip.review.takeaways for clip in selected)
    assert (
        len(
            select_clips(
                (clips[0], clips[0]), skill_id="problem_impact_desire", gap_type="judgment"
            )
        )
        == 1
    )
    assert select_clips(clips, skill_id="qualification", gap_type="judgment") == ()
    assert select_clips(clips, skill_id="problem_impact_desire", gap_type="knowledge") == ()
    assert (
        select_clips(clips, skill_id="problem_impact_desire", gap_type="judgment", topic="other")
        == ()
    )
    assert select_clips(clips, skill_id="report_next_step", gap_type="uncertain") == ()
    with pytest.raises(ValueError, match="one to three"):
        select_clips(clips, skill_id="problem_impact_desire", gap_type="judgment", maximum=4)


def test_forged_approved_clip_is_revalidated_before_selection_or_playback() -> None:
    clip = reviewed_clip(*media())
    forged = clip.model_copy(update={"end_ms": 120_000})
    with pytest.raises(ValidationError):
        select_clips((forged,), skill_id="problem_impact_desire", gap_type="judgment")


def test_preview_uses_explicit_durable_allowance_and_usage_and_never_changes_them() -> None:
    clip = reviewed_clip(*media())
    policy = PreviewAllowance(
        policy_revision="entitlement-v1", full_access=False, preview_ms=1500, clip_limit=2
    )
    usage = PreviewUsage(usage_revision="usage-v1", played_ms=0, clips_started=0)
    window = playback_window(clip, policy, usage)
    assert window.state == "preview" and window.end_ms == 2500
    assert window.action_label == "Get the full coaching"
    assert usage.played_ms == usage.clips_started == 0
    for exhausted in (
        usage.model_copy(update={"played_ms": 1500}),
        usage.model_copy(update={"clips_started": 2}),
    ):
        locked = playback_window(clip, policy, exhausted)
        assert locked.state == "locked" and locked.end_ms is None
    full = playback_window(clip, policy.model_copy(update={"full_access": True}), exhausted)
    assert full.state == "full" and full.end_ms == clip.end_ms
    assert full.action_label is None
    with pytest.raises(ValidationError):
        PreviewAllowance(policy_revision="entitlement-v1", full_access=False)
