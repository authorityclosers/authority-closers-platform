"""Literal named-business fallback from an already verified qualitative C5.

Only the explicit ``company`` fact is a Company name. Person city, industry,
team size and narrative prose never become Company fields. No provider, merge,
identity write or person link is performed here. Absent/ambiguous/private names
yield no candidate; the three other fields remain Unknown.
"""

import json
from collections.abc import Mapping
from typing import Any

from ac_platform.conversation_intelligence.prospect_company_profile import (
    CompanyCandidate,
    CompanyProfileError,
    company_profile_request,
    parse_company_candidate,
)
from ac_platform.conversation_intelligence.prospect_company_projection import (
    company_candidate_digest,
    supported_company_fields,
)
from ac_platform.conversation_intelligence.reports import ReportDraft
from ac_platform.conversation_intelligence.sensitive_segments import EMPTY_PLAN, WithheldPlan

EXTRACTOR_REVISION = "c5-company-facts/1"


def c5_company_candidate(
    report: ReportDraft,
    transcript: Mapping[str, Any],
    *,
    plan: WithheldPlan = EMPTY_PLAN,
) -> CompanyCandidate | None:
    """The caller first verifies source, retention, actor and C5/C2 provenance."""
    try:
        request = company_profile_request(report, transcript)
        if request is None or report.call_map is None:
            return None
        segments = {row["id"]: row for row in request["segments"]}
        candidates: dict[str, CompanyCandidate] = {}
        for fact in report.call_map.prospect_facts:
            if fact.key != "company":
                continue
            for ref in fact.evidence:
                segment = segments.get(ref.segment_id)
                if segment is None:
                    continue
                payload = {
                    **{
                        key: request[key]
                        for key in ("version", "source_sha256", "transcript_revision")
                    },
                    "fields": {
                        "name": {
                            "value": {"kind": "text", "text": fact.text},
                            "evidence": {
                                "segment_id": ref.segment_id,
                                "quote": ref.quote,
                                "start_ms": segment["start_ms"],
                                "end_ms": segment["end_ms"],
                            },
                        }
                    },
                }
                try:
                    candidate = parse_company_candidate(json.dumps(payload), request)
                except CompanyProfileError:
                    continue
                if candidate is None:
                    continue
                name = candidate.fields["name"]["value"]["text"]
                candidates.setdefault(name, candidate)
                break
        if len(candidates) != 1:
            return None
        candidate = next(iter(candidates.values()))
        return (
            candidate
            if supported_company_fields(
                candidate,
                expected_digest=company_candidate_digest(candidate),
                report=report,
                transcript=transcript,
                plan=plan,
            )
            else None
        )
    except (CompanyProfileError, ValueError, TypeError, KeyError):
        return None
