"""Catalogue review and relevance tests use invented Drive metadata only."""

from datetime import UTC, datetime

import pytest

from ac_platform.coaching.catalogue import (
    CatalogueItem,
    TagProposal,
    TagReview,
    match_media,
    reviewed_asset,
)


def asset(kind: str = "audio"):
    item = CatalogueItem(
        drive_id=f"fictional_{kind}_123",
        source_revision="v1",
        category="Coach content",
        title="Explore the impact",
        kind=kind,
        duration_seconds=180,
        dipak_confirmed=True,
    )
    proposal = TagProposal(
        drive_id=item.drive_id,
        source_revision="v1",
        skill_ids=("problem_impact_desire",),
        topics=("consequence questions",),
        gap_types=("judgment",),
        rationale="The fictional asset teaches recognition.",
        provenance="fictional-subscription-handoff",
    )
    review = TagReview(
        drive_id=item.drive_id,
        source_revision="v1",
        decision="approve",
        reviewer_reference="test-reviewer",
        reviewed_at=datetime(2026, 10, 10, tzinfo=UTC),
        reason="Matches the active impact focus.",
        takeaways=("Explore one relevant consequence.",),
    )
    return item, proposal, review


def test_pending_rejected_stale_or_unknown_creator_assets_are_not_teaching_assets() -> None:
    item, proposal, review = asset()
    assert proposal.status == "pending_review"
    assert reviewed_asset(item, proposal, review.model_copy(update={"decision": "reject"})) is None
    assert (
        reviewed_asset(item.model_copy(update={"dipak_confirmed": False}), proposal, review) is None
    )
    with pytest.raises(ValueError, match="exact Drive item revision"):
        reviewed_asset(item, proposal, review.model_copy(update={"source_revision": "v2"}))


def test_relevance_wins_over_format_and_unapproved_content() -> None:
    audio = reviewed_asset(*asset())
    video = reviewed_asset(*asset("video"))
    main, alternative = match_media(
        (video, audio), skill_id="problem_impact_desire", gap_type="judgment"
    )
    assert main == audio and alternative == video
    assert match_media((audio,), skill_id="qualification", gap_type="judgment") == (None, None)
    assert match_media((audio,), skill_id="problem_impact_desire", gap_type="knowledge") == (
        None,
        None,
    )
    assert match_media(
        (audio.model_copy(update={"approved": False}),),
        skill_id="problem_impact_desire",
        gap_type="judgment",
    ) == (None, None)
