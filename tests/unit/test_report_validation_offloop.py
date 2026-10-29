"""The same proof validator runs off-loop over plain loaded data, never ORM objects."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.report_store import ConversationReports


async def test_validator_off_loop_preserves_result_and_exceptions(monkeypatch):
    main = threading.get_ident()
    draft = Mock()
    recording = Mock()
    reports = ConversationReports(SimpleNamespace(database=None))
    result = (Mock(), {"normalized": True})

    def validate(data, source):
        assert threading.get_ident() != main
        assert isinstance(data, SimpleNamespace) and isinstance(source, SimpleNamespace)
        assert data.payload is draft.payload
        assert data.report_sha256 is draft.report_sha256
        assert source.source_revision is recording.source_revision
        return result

    monkeypatch.setattr(reports, "_validated", validate)
    assert await reports.validated(draft, recording) is result

    def reject(*args):
        raise ConversationConflict("proof mismatch")

    monkeypatch.setattr(reports, "_validated", reject)
    with pytest.raises(ConversationConflict, match="proof mismatch"):
        await reports.validated(draft, recording)
