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
# Blind Brain 4.0 mode (21 Oct): one target per dimension and one per correction moment.
DIMENSION_PREFIX = "brain4:"
MOMENT_PREFIX = "moment:"
MAX_MOMENTS = 40
# "-" for a dimension: it did not come up, or it cannot be judged from this call.
DIMENSION_SKIPS = ("not_applicable", "not_sure", "audio_unclear")


def target_kind(target: str) -> Literal["dimension", "moment", "line"]:
    if target.startswith(DIMENSION_PREFIX):
        return "dimension"
    if target.startswith(MOMENT_PREFIX):
        return "moment"
    return "line"


class GoldMoment(BaseModel):
    """One moment the reviewer would correct or praise, at a time in the call. The text is
    the save's ``opinion``. ``caught``: whether Brain 4.0's coaching says the same, marked
    only after its read is shown."""

    model_config = ConfigDict(extra="forbid")

    at_ms: int = Field(ge=0, le=6 * 3600 * 1000, strict=True)
    kind: Literal["criticism", "praise"]
    dimension: str | None = Field(default=None, pattern=r"^D(0[1-9]|1[0-8])$")
    caught: Literal["yes", "partly", "no"] | None = None
    removed: bool = False


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
    # Blind Brain 4.0 mode: a dimension's 1-5 rating, or a correction moment.
    rating: int | None = Field(default=None, ge=1, le=5, strict=True)
    moment: GoldMoment | None = None

    @model_validator(mode="after")
    def judgement(self) -> "GoldSave":
        kind = target_kind(self.target)
        judged = (self.verdict, self.score, self.status)
        if kind == "dimension":
            if any(v is not None for v in judged) or self.reasons or self.moment is not None:
                raise ValueError("Rate a dimension 1-5, or mark it as not rated.")
            if (self.rating is None) == (self.skip is None):
                raise ValueError("Rate a dimension 1-5, or mark it as not rated.")
            if self.skip is not None and self.skip not in DIMENSION_SKIPS:
                raise ValueError("Leave a dimension unsaved to come back to it.")
            return self
        if kind == "moment":
            if any(v is not None for v in judged) or self.reasons or self.rating is not None:
                raise ValueError("A moment carries its time, kind and words only.")
            if self.moment is None or self.skip is not None:
                raise ValueError("A moment needs its time and kind.")
            number = self.target[len(MOMENT_PREFIX) :]
            if not number.isdigit() or not 1 <= int(number) <= MAX_MOMENTS:
                raise ValueError("Choose a moment number.")
            if not self.moment.removed and not self.opinion:
                raise ValueError("Say what happened at this moment.")
            return self
        if self.rating is not None or self.moment is not None:
            raise ValueError("This line takes agree, partly, disagree or a score.")
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
