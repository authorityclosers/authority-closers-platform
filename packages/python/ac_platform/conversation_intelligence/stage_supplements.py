"""Pure matching and cumulative-use helpers for exact-source stage supplements."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from ac_platform.conversation_intelligence.activation_contract import (
    StageApproval,
    StageCallSupplement,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash

_PLAN_EPHEMERAL_FIELDS = frozenset(
    {
        "authority_sha256",
        "created_at_epoch",
        "expires_at_epoch",
        "session_id",
        "processing_lease_id",
        "continuation_grant_id",
    }
)


def processing_plan_sha256(manifest: Mapping[str, Any]) -> str:
    """Hash the admitted plan contract without release/time/lease ephemera.

    The release digest cannot be included because it pins this supplement and
    would create a hash cycle. Quote and plan timestamps plus browser/session
    lease identities are checked by their canonical runtime paths separately.
    Every other manifest field remains covered, so a source, owner/principal,
    route, prompt/profile, language, cap, pack, generation, or budget change
    produces a different fingerprint.
    """

    if not isinstance(manifest, Mapping):
        raise ValueError("processing_plan_manifest_invalid")
    stable = {key: value for key, value in manifest.items() if key not in _PLAN_EPHEMERAL_FIELDS}
    if "authority_sha256" not in manifest or "source_sha256" not in stable:
        raise ValueError("processing_plan_manifest_invalid")
    return content_hash(stable)


@dataclass(frozen=True, slots=True)
class StageSupplementContext:
    tenant_id: UUID
    processing_person_id: UUID
    owner_person_id: UUID
    source_sha256: str
    configuration_sha256: str
    stage: Literal["C5"]
    recipe_revision: str
    coaching_prompt_revision: Literal["coaching-v4"]
    report_language: Literal["en", "hi-Deva+en", "mr-Deva+en"]
    processing_plan_sha256: str
    prepared_input_sha256: str


def matches_stage_supplement(
    supplement: StageCallSupplement,
    approval: StageApproval,
    context: StageSupplementContext,
    *,
    now_epoch: int,
) -> bool:
    """Match every owner, source, route, prompt, and time binding exactly."""

    return (
        type(now_epoch) is int
        and supplement.issued_at_epoch <= now_epoch < supplement.expires_at_epoch
        and supplement.base_approval_id == approval.id
        and supplement.tenant_id == context.tenant_id == approval.tenant_id
        and supplement.processing_person_id == context.processing_person_id == approval.person_id
        and supplement.owner_person_id == context.owner_person_id
        and supplement.source_sha256 == context.source_sha256 == approval.source_sha256
        and supplement.configuration_sha256
        == context.configuration_sha256
        == approval.configuration_sha256
        and supplement.stage == context.stage == approval.stage == "C5"
        and supplement.recipe_revision == context.recipe_revision == approval.recipe_revision
        and supplement.coaching_prompt_revision == context.coaching_prompt_revision
        and supplement.report_language == context.report_language
        and supplement.processing_plan_sha256 == context.processing_plan_sha256
        and supplement.prepared_input_sha256 == context.prepared_input_sha256
    )


def supplemental_reservations(
    reservations: tuple[object, ...], *, base_max_requests: int
) -> tuple[int, int]:
    """Return count and maximum-cost sum beyond the unchanged base slots.

    The reservation sequence is append-only. Released reservations still
    consume a request slot, matching the existing authority counter, and are
    conservatively included at their quoted maximum cost.
    """

    if type(base_max_requests) is not int or base_max_requests < 0:
        raise ValueError("base_request_limit_invalid")
    extras = reservations[base_max_requests:]
    count = len(extras)
    cost = 0
    for entry in extras:
        quote = getattr(entry, "quote", None)
        maximum = getattr(quote, "max_cost_paise", None)
        if type(maximum) is not int or maximum < 0:
            raise ValueError("reservation_quote_invalid")
        cost += maximum
    return count, cost
