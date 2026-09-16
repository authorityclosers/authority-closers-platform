"""Strict external contracts; caller data does not confer execution authority."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[str, Field(min_length=1, max_length=128)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecordingIntent(Contract):
    source_sha256: Digest
    source_bytes: StrictInt = Field(gt=0, le=MAX_AUDIO_BYTES)
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
    source_bytes: StrictInt = Field(gt=0, le=MAX_AUDIO_BYTES)
    content_type: Literal["audio/mpeg", "audio/wav", "audio/ogg", "audio/flac", "audio/mp4"]
    duration_ms: StrictInt = Field(gt=0, le=7200000)
    purpose: Literal["internal_analysis"]


class QuoteAcceptance(Contract):
    quote_fingerprint: Digest
    privacy_revision: Revision
    accepted: Literal[True]


C5RepairFailureCode = Literal[
    "conversation_report_evidence_quote_mismatch",
    "conversation_report_evidence_segment_invalid",
    "conversation_report_findings_invalid",
    "conversation_report_dimension_status_invalid",
    "conversation_report_overview_missing",
    "conversation_report_json_invalid",
]

C5_REPAIR_FAILURE_CODES = frozenset(
    {
        "conversation_report_evidence_quote_mismatch",
        "conversation_report_evidence_segment_invalid",
        "conversation_report_findings_invalid",
        "conversation_report_dimension_status_invalid",
        "conversation_report_overview_missing",
        "conversation_report_json_invalid",
    }
)


class C5RepairIntent(Contract):
    """One server-created repair of a returned, structurally invalid C5 object."""

    attempt: Literal[1] = 1
    failure_code: C5RepairFailureCode
    original_run_id: UUID
    original_response_sha256: Digest


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
