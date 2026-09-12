"""Strict external contracts; caller data does not confer execution authority."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[str, Field(min_length=1, max_length=128)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecordingIntent(Contract):
    source_sha256: Digest
    source_bytes: StrictInt = Field(gt=0, le=134217728)
    content_type: Literal["audio/mpeg", "audio/wav", "audio/ogg", "audio/flac", "audio/mp4"]
    permission_reference: UUID
    purpose: Literal["internal_analysis"]


class RunIntent(Contract):
    recording_id: UUID
    source_revision: Revision
    quote_id: UUID
    recipe_revision: Revision


class IntakeIntent(Contract):
    source_sha256: Digest
    source_bytes: StrictInt = Field(gt=0, le=134217728)
    content_type: Literal["audio/mpeg", "audio/wav", "audio/ogg", "audio/flac", "audio/mp4"]
    duration_ms: StrictInt = Field(gt=0, le=7200000)
    purpose: Literal["internal_analysis"]


class QuoteAcceptance(Contract):
    quote_fingerprint: Digest
    privacy_revision: Revision
    accepted: Literal[True]


class ReviewIntent(Contract):
    run_revision: Revision
    transcript_revision: Revision
    measurement_revision: Revision
    profile_revision: Revision
    lane: Literal["contextual", "measurement"]
    target: str = Field(min_length=1, max_length=128)
    kind: Literal["agree", "partly", "incorrect", "insufficient_context"]
    note: str = Field(min_length=1, max_length=4000)


class Capabilities(Contract):
    product: Literal["Sales Xray"] = "Sales Xray"
    intake: Literal["unavailable", "enabled"] = "unavailable"
    provider_processing: Literal["disabled"] = "disabled"
    numeric_publication: Literal["withheld"] = "withheld"
    local_checkpoint_import: bool = True
    reasons: tuple[str, ...] = (
        "Local checkpoint inspection is available.",
        "Server recording intake requires the configured internal workspace.",
        "External provider processing has not been activated.",
    )
