"""Reviewer inputs; AI values are always selected by the server."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GoldSave(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    review_id: UUID
    target: str = Field(min_length=1, max_length=96)
    verdict: Literal["agree", "partly", "disagree"] | None = None
    score: int | None = Field(default=None, ge=0, le=100, strict=True)
    opinion: str = Field(min_length=1, max_length=4000)
    supersedes_id: UUID | None = None

    @model_validator(mode="after")
    def judgement(self) -> "GoldSave":
        if self.verdict is None and self.score is None:
            raise ValueError("Choose agree, partly, disagree or a score.")
        return self


class GoldDesignation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320)
    active: bool = True
