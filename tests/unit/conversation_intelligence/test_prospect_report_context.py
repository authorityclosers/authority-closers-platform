"""Source wording, rather than generated task prose, enters report context."""

from typing import Any

import pytest

from ac_platform.conversation_intelligence.call_map import parse_call_map
from ac_platform.conversation_intelligence.prospect_library import _context_quotes
from ac_platform.conversation_intelligence.reports import parse_report_draft
from tests.unit.conversation_intelligence.test_call_map import _call_map, _segments
from tests.unit.conversation_intelligence.test_reports import _payload, _transcript


@pytest.mark.parametrize("unsupported", [False, True])
def test_task_promises_retain_literal_support_and_omit_invented_wording(unsupported: bool) -> None:
    payload = _call_map()
    task = payload["seller_tasks"][0]
    if unsupported:
        task["evidence"][0]["quote"] = "I will send the layout tomorrow."
    transcript = _transcript()
    report = parse_report_draft(_payload(transcript), transcript).model_copy(
        update={"call_map": parse_call_map(payload)}
    )
    segments: dict[str, Any] = {segment["id"]: segment for segment in _segments()}
    quotes = _context_quotes(report, [], segments)
    assert ("I can send the layout today." in str(quotes)) is not unsupported
    assert "I will send the layout tomorrow." not in str(quotes)
    assert task["text"] not in str(quotes)
    assert all(ref["quote"] in segments[ref["segment_id"]]["text"] for ref in quotes)
    assert all(ref["start_ms"] == segments[ref["segment_id"]]["start_ms"] for ref in quotes)
