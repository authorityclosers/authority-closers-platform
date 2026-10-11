"""Pure Company facts; storage/source authority remains with the caller.

The read validator accepts only a pinned candidate over an already verified,
currently readable C5/C2 pair. It does not grant access, choose a report, run a
provider, create an identity or link a person. Projection consumes only human
revisions and heard revisions which have passed that boundary.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.prospect_company_fields import (
    COMPANY_FIELD_REGISTRY,
    validate_company_fields,
)
from ac_platform.conversation_intelligence.prospect_company_profile import (
    MAX_OUTPUT_BYTES,
    CompanyCandidate,
    CompanyProfileError,
    company_profile_request,
    parse_company_candidate,
)
from ac_platform.conversation_intelligence.prospect_fact_contract import ProspectFactValidationError
from ac_platform.conversation_intelligence.reports import ReportDraft
from ac_platform.conversation_intelligence.sensitive_segments import (
    EMPTY_PLAN,
    WITHHELD_MARKER,
    WithheldPlan,
    strings,
    withhold,
)


def company_candidate_payload(candidate: CompanyCandidate) -> dict[str, Any]:
    return {
        "version": candidate.version,
        "source_sha256": candidate.source_sha256,
        "transcript_revision": candidate.transcript_revision,
        "fields": candidate.fields,
    }


def company_candidate_digest(candidate: CompanyCandidate) -> str:
    """Pin the whole candidate, including original business name and evidence."""
    return content_hash(company_candidate_payload(candidate))


def supported_company_fields(
    candidate: CompanyCandidate,
    *,
    expected_digest: str,
    report: ReportDraft,
    transcript: Mapping[str, Any],
    plan: WithheldPlan = EMPTY_PLAN,
) -> dict[str, dict[str, Any]]:
    """Recheck literal value, business subject, native time/role and privacy.

    Invalid/missing source returns no heard fields. A private purpose or name
    withholds the candidate; a private attribute withholds only that attribute.
    Human edits are outside this function and never inherit source quotes.
    """
    try:
        payload = company_candidate_payload(candidate)
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw.encode()) > MAX_OUTPUT_BYTES or content_hash(payload) != expected_digest:
            return {}
        request = company_profile_request(report, transcript)
        if request is None:
            return {}
        checked = parse_company_candidate(raw, request)
        if checked is None or report.call_map is None:
            return {}
        purpose = [ref.model_dump(mode="json") for ref in report.call_map.call_purpose.evidence]
        if WITHHELD_MARKER in strings(withhold(purpose, plan)):
            return {}
        visible = {
            key: item
            for key, item in checked.fields.items()
            if WITHHELD_MARKER not in strings(withhold(item, plan))
        }
        return visible if "name" in visible else {}
    except (CompanyProfileError, ProspectFactValidationError, ValueError, TypeError, KeyError):
        return {}


@dataclass(frozen=True)
class CompanyFactRevision:
    """Detached read value, copied only after entity and source admission."""

    id: UUID
    field_key: str
    revision: int
    value: dict[str, Any]
    basis: Literal["person", "heard_in_call"]
    created_at: datetime
    created_by_person_id: UUID | None = None
    submission_id: UUID | None = None
    evidence: dict[str, Any] | None = None
    supersedes_id: UUID | None = None


def project_company_fields(
    history: Sequence[CompanyFactRevision], *, detected: bool
) -> dict[str, Any]:
    """Human locks win; bounded visible later disagreements remain hypotheses.

    Sequence order is irrelevant. Unknown entered by a person hides old values
    and their evidence. Changed compares only an exact visible superseded heard
    revision of this field; a different field cannot become its history.
    """
    fields: dict[str, Any] = {}
    for key in COMPANY_FIELD_REGISTRY:
        revisions = sorted(
            (item for item in history if item.field_key == key),
            key=lambda item: item.revision,
            reverse=True,
        )
        person = next((item for item in revisions if item.basis == "person"), None)
        current = person or next(iter(revisions), None)
        if current is None:
            fields[key] = {
                "state": "unknown",
                "reason": "not_mentioned" if detected else "not_asked",
            }
            continue
        try:
            value = validate_company_fields({key: current.value})[key]
        except ProspectFactValidationError:
            fields[key] = {"state": "unknown", "reason": "not_mentioned"}
            continue
        meta: dict[str, Any] = {
            "basis": current.basis,
            "locked": person is not None,
            "set_at": current.created_at.isoformat(),
        }
        if person:
            meta["set_by"] = str(person.created_by_person_id)
        if value["kind"] == "unknown":
            fields[key] = {"state": "unknown", "reason": value["reason"], **meta}
            continue
        projected: dict[str, Any] = {"state": "known", "value": value, **meta}

        def source(item: CompanyFactRevision) -> dict[str, Any]:
            return {
                "value": item.value,
                "set_at": item.created_at.isoformat(),
                "evidence": {"submission_id": str(item.submission_id), **(item.evidence or {})},
            }

        if person:
            different = [
                item
                for item in revisions
                if item.basis == "heard_in_call"
                and item.revision > person.revision
                and item.value != value
                and item.value.get("kind") == "text"
            ]
            if different:
                projected["heard_differently"] = [source(item) for item in different[:5]]
        else:
            projected["evidence"] = source(current)["evidence"]
            previous = next(
                (
                    item
                    for item in revisions
                    if item.id == current.supersedes_id
                    and item.basis == "heard_in_call"
                    and item.value != value
                    and item.value.get("kind") == "text"
                    and item.created_at < current.created_at
                ),
                None,
            )
            if previous:
                projected["changed_from"] = source(previous)
        fields[key] = projected
    return fields
