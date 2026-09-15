import hashlib
import json
import time

import pytest

from ac_platform.conversation_intelligence import approved_call_test as runner
from ac_platform.conversation_intelligence.providers import ProviderError, ProviderResult
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage


def setup(tmp_path):
    root = PrivateLocalRecordingStorage(tmp_path / "private").root
    source = tmp_path / "approved.wav"
    source.write_bytes(b"synthetic-local-test")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    approval = {
        "approved": True,
        "max_paid_paise": 0,
        "expires_at_epoch": int(time.time()) + 600,
        "providers": ["elevenlabs:scribe_v2", "groq:openai/gpt-oss-120b"],
        "test_id": "test-one",
        "source_path": str(source),
        "source_bytes": source.stat().st_size,
        "duration_ms": 1000,
        "source": {
            "tenant_id": "a",
            "recording_id": "r",
            "source_sha256": sha,
            "source_revision": "1",
        },
        "privacy_revision": "test-only",
        "authorization_ref": "test-owner-consent",
        "terms": {"elevenlabs": "synthetic-test"},
        "retention": {"elevenlabs": "delete-test"},
        "allowance_ref": "test-zero-paid",
    }
    runner.write_private(root / "approval.json", approval)
    return root, source, approval


def test_exact_source_and_current_permission_checked_before_dispatch(tmp_path, monkeypatch):
    root, source, _ = setup(tmp_path)
    monkeypatch.setattr(runner, "BoundedProviders", lambda **kwargs: pytest.fail("No dispatch"))
    source.write_bytes(b"changed")
    with pytest.raises(ProviderError, match="source_mismatch"):
        runner.execute(root, "transcript")
    assert not (root / "transcript-journal.jsonl").exists()


def test_native_response_persisted_and_journal_blocks_retranscription(tmp_path, monkeypatch):
    root, _, approval = setup(tmp_path)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "synthetic-secret")
    native = {
        "text": "Hello there",
        "words": [{"text": "Hello there", "start": 0, "end": 1, "speaker_id": "speaker_0"}],
    }
    raw = json.dumps(native).encode()
    calls = []

    class Fake:
        def __init__(self, *, credentials, authorize):
            self.authorize = authorize
            assert credentials == {"elevenlabs": "synthetic-secret"}

        def transcribe(self, reservation, data):
            self.authorize(reservation)
            journal = (root / "transcript-journal.jsonl").read_text()
            assert '"event":"reserved"' in journal and '"event":"in_flight"' in journal
            calls.append(1)
            return ProviderResult(
                "elevenlabs",
                "scribe_v2",
                "synthetic-id",
                hashlib.sha256(raw).hexdigest(),
                raw,
                native,
                {},
                approval["source"]["source_sha256"],
            )

    monkeypatch.setattr(runner, "BoundedProviders", Fake)
    result = runner.execute(root, "transcript")
    assert result["segment_count"] == 1
    assert (root / "transcript-native.json").read_bytes() == raw
    assert "synthetic-secret" not in (root / "transcript-journal.jsonl").read_text()
    with pytest.raises(FileExistsError):
        runner.execute(root, "transcript")
    assert calls == [1]


def test_denied_approval_never_dispatches(tmp_path, monkeypatch):
    root, _, approval = setup(tmp_path)
    approval["approved"] = False
    (root / "approval.json").write_text(json.dumps(approval))
    monkeypatch.setattr(runner, "BoundedProviders", lambda **kwargs: pytest.fail("No dispatch"))
    with pytest.raises(ProviderError, match="approval_required"):
        runner.execute(root, "transcript")
