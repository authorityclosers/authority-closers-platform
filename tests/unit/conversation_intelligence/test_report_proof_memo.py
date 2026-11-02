"""A report is parsed, and a report read's durable chain proved, once per process for the same
draft content (the test robot, 2 Nov 2026: a seller's Coaching parsed and proved all 20 reports
again on every visit, 3.5-5.4 s). The content hashes are still checked on every read, and any
change to the draft, its recording or a chain row checks it again."""

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence import report_store
from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.report_store import ConversationReports, ProvenDrafts
from ac_platform.conversation_intelligence.reports import load_report_profile, parse_report_draft
from tests.unit.conversation_intelligence.test_coaching_v5_integration import successor_case


@pytest.fixture(autouse=True)
def proven(monkeypatch: pytest.MonkeyPatch) -> ProvenDrafts:
    memo = ProvenDrafts()
    monkeypatch.setattr(ConversationReports, "proven", memo)
    return memo


def durable_case() -> tuple[SimpleNamespace, SimpleNamespace]:
    """A saved durable draft and its recording, as test_coaching_v5_integration builds them."""
    transcript, _, draft = successor_case()
    transcript["revision"] = "b" * 64
    profile = load_report_profile()
    report = parse_report_draft(draft, transcript, coaching_prompt_revision="coaching-v5")
    payload = report.model_dump(mode="json")
    recording = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        person_id=uuid4(),
        source_revision=1,
        source_sha256=transcript["source_sha256"],
        generation=1,
    )
    proof = {
        "schema_id": "ac.sales-xray.durable-draft-proof/1",
        "transcript_checkpoint_id": str(uuid4()),
        "transcription_task_id": str(uuid4()),
        "transcription_response_sha256": transcript["revision"],
        "coaching_checkpoint_id": str(uuid4()),
        "presentation_checkpoint_id": str(uuid4()),
        "coaching_response_sha256": "c" * 64,
        "accepted_quote_id": str(uuid4()),
        "profile_sha256": content_hash(profile),
        "human_approved": False,
        "numeric_publication": False,
    }
    source = {
        "normalized": transcript,
        "profile": profile,
        "native_response_ref": {
            "task_id": proof["transcription_task_id"],
            "response_sha256": transcript["revision"],
        },
    }
    stored = SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        recording_id=recording.id,
        tenant_id=recording.tenant_id,
        person_id=recording.person_id,
        source_revision=recording.source_revision,
        source_sha256=recording.source_sha256,
        erased_at=None,
        payload=payload,
        report_sha256=content_hash(payload),
        transcript=source,
        transcript_sha256=content_hash(source),
        evidence_receipt=proof,
        evidence_receipt_sha256=content_hash(proof),
        profile_sha256=content_hash(profile),
    )
    return stored, recording


def test_a_draft_is_parsed_once_and_its_content_still_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed: list[int] = []
    real = report_store.parse_report_draft

    def counting(*args: Any, **kwargs: Any) -> Any:
        parsed.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(report_store, "parse_report_draft", counting)
    stored, recording = durable_case()
    first, transcript = ConversationReports._validated(stored, recording)
    again, transcript_again = ConversationReports._validated(stored, recording)
    assert len(parsed) == 1
    assert again.model_dump(mode="json") == first.model_dump(mode="json") == stored.payload
    assert transcript_again == transcript == stored.transcript["normalized"]

    # Content that no longer matches its hash fails at once, proved before or not.
    original = stored.payload["dimensions"][0]["evidence"][0]["quote"]
    stored.payload["dimensions"][0]["evidence"][0]["quote"] = "Not present in the source."
    with pytest.raises(ConversationConflict, match="evidence is unavailable"):
        ConversationReports._validated(stored, recording)
    # Changed and hashed again, it is new content: proved again, and it fails.
    stored.report_sha256 = content_hash(stored.payload)
    with pytest.raises(ConversationConflict, match="needs review"):
        ConversationReports._validated(stored, recording)
    assert len(parsed) == 2

    # Back to the proved content: an erased draft never reads, proved or not.
    stored.payload["dimensions"][0]["evidence"][0]["quote"] = original
    stored.report_sha256 = content_hash(stored.payload)
    ConversationReports._validated(stored, recording)
    stored.erased_at = "2026-11-02T00:00:00+00:00"
    with pytest.raises(ConversationConflict, match="evidence is unavailable"):
        ConversationReports._validated(stored, recording)


def test_another_recording_parses_again(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed: list[int] = []
    real = report_store.parse_report_draft

    def counting(*args: Any, **kwargs: Any) -> Any:
        parsed.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(report_store, "parse_report_draft", counting)
    stored, recording = durable_case()
    ConversationReports._validated(stored, recording)
    recording.source_revision = 2
    stored.source_revision = 2
    ConversationReports._validated(stored, recording)
    assert len(parsed) == 2


def test_a_report_read_keeps_a_proved_chain_until_a_row_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The orchestrator's rules (2 Nov 2026): a durable chain is proved once per
    report version, keyed by the report's content hashes and a digest of every
    chain row, and proved again whenever either changes; integrity checks read
    the whole chain every time."""
    chains: list[Any] = []
    rows = ["digest-1"]
    failing = [False]

    async def chain(self: Any, draft: Any, recording: Any) -> None:
        chains.append(draft.id)
        if failing[0]:
            raise ConversationConflict("The stored report's canonical evidence differs.")

    async def chain_rows(self: Any, recording: Any) -> str:
        return rows[0]

    monkeypatch.setattr(ConversationReports, "_canonical_chain", chain)
    monkeypatch.setattr(ConversationReports, "_chain_rows", chain_rows)
    reports = ConversationReports.__new__(ConversationReports)
    stored, recording = durable_case()

    def read(memo: bool = True) -> None:
        asyncio.run(reports._canonical_draft(stored, recording, memo=memo))

    read()
    read()
    assert len(chains) == 1
    # An integrity check reads the whole chain, cached or not.
    read(memo=False)
    assert len(chains) == 2
    # A chain row changed (a tampered receipt, say): proved again, and caught.
    rows[0] = "digest-2"
    failing[0] = True
    for _ in range(2):
        with pytest.raises(ConversationConflict):
            read()
    assert len(chains) == 4
    # A changed report is another key too.
    failing[0] = False
    stored.report_sha256 = "f" * 64
    read()
    assert len(chains) == 5
    # A private (not durable) draft has no chain to read.
    stored.evidence_receipt = {"schema_id": "ac.sales-xray.private-proof-reference/1"}
    read()
    assert len(chains) == 5


def test_the_memo_is_bounded_and_forgets() -> None:
    memo = ProvenDrafts(capacity=2, ttl_seconds=60)
    for key in [("a",), ("b",), ("c",)]:
        memo.remember(key)
    assert not memo.seen(("a",)) and memo.seen(("b",)) and memo.seen(("c",))
    gone = ProvenDrafts(ttl_seconds=0)
    gone.remember(("a",))
    assert not gone.seen(("a",))
