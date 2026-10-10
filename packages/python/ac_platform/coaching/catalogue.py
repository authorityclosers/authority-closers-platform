"""Reviewed Drive catalogue contracts, independent of providers and billing.

Import metadata by stable Drive ID from a root-exported manifest. AI tag proposals
are inputs from the authorized subscription workflow; they remain in the review
queue until an attributable review approves their exact source revision. This
module does not open root's index, fetch guessed filenames, or invoke paid AI.
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ac_platform.coaching.contracts import GapType, LearningAsset, Model
from ac_platform.coaching.report_adapter import SKILLS

Category = Literal["Courses", "Sales training recordings", "Content library", "Coach content"]


class CatalogueItem(Model):
    drive_id: str = Field(pattern=r"^[A-Za-z0-9_-]{10,200}$")
    source_revision: str = Field(min_length=1, max_length=256)
    category: Category
    title: str = Field(min_length=1, max_length=256)
    kind: Literal["audio", "video"]
    duration_seconds: int | None = Field(default=None, gt=0)
    # Metadata alone must not invent creator identity or permission to teach.
    dipak_confirmed: bool = False


class TagProposal(Model):
    drive_id: str
    source_revision: str
    skill_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    topics: tuple[str, ...] = Field(min_length=1, max_length=12)
    gap_types: tuple[GapType, ...] = Field(min_length=1, max_length=11)
    rationale: str = Field(min_length=1, max_length=2000)
    provenance: str = Field(min_length=1, max_length=256)
    status: Literal["pending_review"] = "pending_review"

    @model_validator(mode="after")
    def supported_skills(self) -> "TagProposal":
        if not set(self.skill_ids) <= SKILLS or any(not topic.strip() for topic in self.topics):
            raise ValueError("Tags must name supported skills and nonblank topics.")
        return self


class TagReview(Model):
    drive_id: str
    source_revision: str
    decision: Literal["approve", "reject"]
    reviewer_reference: str = Field(min_length=1, max_length=256)
    reviewed_at: datetime
    reason: str = Field(min_length=1, max_length=1000)
    takeaways: tuple[str, ...] = Field(min_length=1, max_length=5)


def reviewed_asset(
    item: CatalogueItem,
    proposal: TagProposal,
    review: TagReview,
) -> LearningAsset | None:
    if (
        item.drive_id != proposal.drive_id
        or item.drive_id != review.drive_id
        or item.source_revision != proposal.source_revision
        or item.source_revision != review.source_revision
    ):
        raise ValueError("Review must bind the exact Drive item revision.")
    if review.decision != "approve" or not item.dipak_confirmed or item.duration_seconds is None:
        return None
    if re.fullmatch(r"[A-Za-z0-9_-]{10,200}", item.drive_id) is None:
        raise ValueError("A stable Drive ID is required.")
    return LearningAsset(
        asset_id=item.drive_id,
        title=item.title,
        kind=item.kind,
        skill_ids=proposal.skill_ids,
        topics=proposal.topics,
        gap_types=proposal.gap_types,
        duration_seconds=item.duration_seconds,
        url=f"https://drive.google.com/file/d/{item.drive_id}/view",
        approved=True,
        relevance=review.reason,
        takeaways=review.takeaways,
    )


def match_media(
    assets: tuple[LearningAsset, ...],
    *,
    skill_id: str,
    gap_type: GapType,
) -> tuple[LearningAsset | None, LearningAsset | None]:
    eligible = [
        a
        for a in assets
        if a.approved
        and skill_id in a.skill_ids
        and (gap_type == "uncertain" or gap_type in a.gap_types)
    ]
    # Specific skill matches first; audio is the default only when equally
    # relevant. No learner-format preference is invented from content views.
    eligible.sort(key=lambda a: (len(a.skill_ids), a.kind != "audio", a.asset_id))
    if not eligible:
        return None, None
    main = eligible[0]
    alternative = next((a for a in eligible[1:] if a.kind != main.kind), None)
    return main, alternative
