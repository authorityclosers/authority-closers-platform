"""Reviewer inputs; AI values are always selected by the server."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The AI's own status words, so a reviewer can say which one was right.
GoldStatus = Literal[
    "excellent",
    "good",
    "average",
    "needs_improvement",
    "not_observed",
    "not_applicable",
    "insufficient_evidence",
]
# Why the reviewer disagrees (or only partly agrees): a fixed list, so they count.
GoldReason = Literal[
    "wrong_evidence",
    "missed_evidence",
    "too_harsh",
    "too_generous",
    "wrong_status",
    "misheard",
    "wrong_speaker",
    "not_relevant",
    "feedback_unclear",
    "other",
]
GoldSkip = Literal["audio_unclear", "not_sure", "not_applicable", "come_back"]


class GoldSave(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    review_id: UUID
    target: str = Field(min_length=1, max_length=96)
    verdict: Literal["agree", "partly", "disagree"] | None = None
    score: int | None = Field(default=None, ge=0, le=100, strict=True)
    # Phone review (19 Oct): the note is optional; the Admin form still asks for one.
    opinion: str = Field(default="", max_length=4000)
    status: GoldStatus | None = None
    reasons: list[GoldReason] = Field(default_factory=list, max_length=6)
    skip: GoldSkip | None = None
    # Seconds the reviewer spent on this line, measured by the page (time per item).
    seconds: int | None = Field(default=None, ge=0, le=3600, strict=True)
    supersedes_id: UUID | None = None

    @model_validator(mode="after")
    def judgement(self) -> "GoldSave":
        if self.skip is not None:
            if self.verdict is not None or self.score is not None or self.status is not None:
                raise ValueError("A skipped line carries no judgement.")
            return self
        if self.verdict is None and self.score is None:
            raise ValueError("Choose agree, partly, disagree or a score.")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("Choose each reason once.")
        return self


class GoldDesignation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320)
    active: bool = True
