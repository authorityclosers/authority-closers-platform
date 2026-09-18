"""Lossless support for retained provider singleton citations, never new facts."""

from copy import deepcopy
from typing import Any

import pytest

from ac_platform.conversation_intelligence.reports import ReportError, parse_report_draft
from tests.conversation_overview_fixtures import overview_for
from tests.unit.conversation_intelligence.test_reports import _evidence, _payload, _transcript


def test_singleton_citations_match_explicit_arrays_without_mutating_provider_output() -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    expected = parse_report_draft(payload, transcript).model_dump(mode="json")

    def singular(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "evidence" and isinstance(child, list) and len(child) == 1:
                    value[key] = child[0]
                else:
                    singular(child)
        elif isinstance(value, list):
            for child in value:
                singular(child)

    singular(payload["overview"])
    retained_response = deepcopy(payload)
    assert parse_report_draft(payload, transcript).model_dump(mode="json") == expected
    assert payload == retained_response


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quote", "invented words"),
        ("segment_id", "not-a-source-segment"),
        ("start_ms", 1),
        ("end_ms", 999_999),
        ("extra_claim", "not approved"),
    ],
)
def test_singleton_citations_keep_source_and_schema_guards(field: str, value: Any) -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    evidence = deepcopy(_evidence(transcript))
    evidence[field] = value
    payload["overview"]["diagnosis"] = {"text": "Source-bound diagnosis", "evidence": evidence}
    with pytest.raises(ReportError):
        parse_report_draft(payload, transcript)


@pytest.mark.parametrize("value", [None, {}, "citation", [[{"quote": "words"}]]])
def test_other_evidence_shapes_are_not_coerced(value: Any) -> None:
    transcript = _transcript()
    payload = _payload(transcript)
    payload["overview"] = overview_for(payload)
    payload["overview"]["diagnosis"] = {"text": "Source-bound diagnosis", "evidence": value}
    with pytest.raises(ReportError):
        parse_report_draft(payload, transcript)
