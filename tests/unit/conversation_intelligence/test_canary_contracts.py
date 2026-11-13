"""Staging's canary checks C4/C5 offline (orchestrator, 13 Nov 2026): no paid call."""

import pytest

from ac_platform.conversation_intelligence import canary_contracts
from ac_platform.conversation_intelligence.canary_contracts import check_stage_contracts


@pytest.mark.parametrize("revision", ["coaching-v4", "coaching-v5"])
def test_the_fixture_passes_this_releases_c4_and_c5_validators(revision: str) -> None:
    assert check_stage_contracts(revision) == {"C4": "ok", "C5": "ok", "c5_revision": revision}


def test_no_revision_reads_as_the_parsers_default() -> None:
    assert check_stage_contracts(None)["c5_revision"] == "coaching-v4"


def test_a_revision_without_a_fixture_fails_closed() -> None:
    # A newer C5 shape needs its own fixture before staging switches to it.
    with pytest.raises(ValueError, match=canary_contracts.UNAVAILABLE):
        check_stage_contracts("coaching-v8")


def test_a_malformed_c4_answer_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(canary_contracts.C4_ANSWER, "observations", "not a list")
    with pytest.raises(ValueError):
        check_stage_contracts("coaching-v5")


def test_a_c5_claim_without_its_source_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    real = canary_contracts.coaching_answer

    def unsupported(profile):
        answer = real(profile)
        answer["dimensions"][0]["evidence"] = [{"segment_id": "s9"}]
        return answer

    monkeypatch.setattr(canary_contracts, "coaching_answer", unsupported)
    with pytest.raises(ValueError):
        check_stage_contracts("coaching-v5")
