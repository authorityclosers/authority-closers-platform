"""Catalogue review and relevance tests use invented Drive metadata only."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ac_platform.coaching.catalogue import (
    CatalogueItem,
    TagProposal,
    TagReview,
    match_media,
    review_subject_sha256,
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
        subject_sha256=review_subject_sha256(item, proposal),
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
    unconfirmed = item.model_copy(update={"dipak_confirmed": False})
    assert (
        reviewed_asset(
            unconfirmed,
            proposal,
            review.model_copy(
                update={"subject_sha256": review_subject_sha256(unconfirmed, proposal)}
            ),
        )
        is None
    )
    with pytest.raises(ValueError, match="exact Drive item revision"):
        reviewed_asset(item, proposal, review.model_copy(update={"source_revision": "v2"}))


@pytest.mark.parametrize(
    "change",
    [
        {"skill_ids": ("qualification",)},
        {"gap_types": ("knowledge",)},
        {"topics": ("a different lesson",)},
        {"rationale": "A later content claim needs review."},
        {"provenance": "a different handoff"},
    ],
)
def test_changed_tag_proposal_cannot_reuse_an_earlier_review(change) -> None:
    item, proposal, review = asset()
    with pytest.raises(ValueError, match="exact catalogue item and tag proposal"):
        reviewed_asset(item, proposal.model_copy(update=change), review)


def test_changed_item_metadata_and_forged_creator_flag_cannot_reuse_a_review() -> None:
    item, proposal, review = asset()
    for change in ({"title": "A different title"}, {"duration_seconds": 500}):
        with pytest.raises(ValueError, match="exact catalogue item and tag proposal"):
            reviewed_asset(item.model_copy(update=change), proposal, review)
    with pytest.raises(ValidationError):
        reviewed_asset(item.model_copy(update={"dipak_confirmed": "false"}), proposal, review)


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
