"""Dormant names-free C5 context; fictional attribution never verifies voice."""

from copy import deepcopy

import pytest

from ac_platform.conversation_intelligence import reports
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.speaker_map import project_speaker_roles
from ac_platform.conversation_intelligence.speaker_roles import validate_speaker_roles
from tests.unit.conversation_intelligence.test_coaching_source_context import (
    prompt_payload,
    source_and_facts,
)


def snapshot(origin="user_confirmed_roles"):
    return {
        "origin": origin,
        "transcript_revision": "scribe-response-r1",
        "map_revision": "a" * 64,
        "speakers": [{"speaker_id": "speaker_1", "role": "seller", "is_account_holder": True}],
    }


@pytest.mark.parametrize("revision", [f"coaching-v{n}" for n in range(1, 7)])
def test_undeclared_revisions_omit_roles_byte_for_byte(revision):
    assert revision not in reports.SPEAKER_ROLE_PROMPT_REVISIONS
    transcript, packet = source_and_facts()
    options = dict(provider="gemini", model="gemini-3.8-flash", coaching_prompt_revision=revision)
    if revision in {"coaching-v4", "coaching-v5", "coaching-v6"}:
        options["qualitative_pack_sha256"] = load_qualitative_pack_for_revision(revision).sha256
    before = deepcopy((transcript, packet))
    baseline, _ = prompt_payload(transcript, packet, **options)
    selected, payload = prompt_payload(transcript, packet, speaker_roles=snapshot(), **options)
    assert selected == baseline
    assert "speaker_roles" not in payload["source_context"]
    assert (transcript, packet) == before


def test_declaring_context_detaches_snapshot_preserves_c2_and_validates(monkeypatch):
    monkeypatch.setattr(reports, "SPEAKER_ROLE_PROMPT_REVISIONS", frozenset({"coaching-v3"}))
    transcript, packet = source_and_facts()
    roles = snapshot()
    before = deepcopy((transcript, packet, roles))
    _, payload = prompt_payload(
        transcript, packet, coaching_prompt_revision="coaching-v3", speaker_roles=roles
    )
    context = payload["source_context"]
    assert context["speaker_identity"] == roles["origin"]
    assert context["speaker_roles"] == roles
    assert context["rows"] == reports.coaching_source_context(transcript)["rows"]
    reports.validate_coaching_context(payload)
    assert (transcript, packet, roles) == before
    roles["speakers"][0]["role"] = "other"
    assert context["speaker_roles"] == before[2]
    context["speaker_identity"] = "voice_match"
    with pytest.raises(reports.ReportError, match="^report_source_context_invalid$"):
        reports.validate_coaching_context(payload)


@pytest.mark.parametrize(
    "role,projected,holder",
    [
        ("you", "seller", True),
        ("salesperson", "seller", False),
        ("prospect", "prospect", False),
        ("other", "other", False),
    ],
)
def test_existing_role_projection_is_names_free(role, projected, holder):
    value = project_speaker_roles(
        {
            "transcript_revision": "scribe-response-r1",
            "map_revision": "a" * 64,
            "speakers": [
                {
                    "speaker_id": "speaker_1",
                    "role": role,
                    "role_source": "confirmed",
                    "display_name": "Fictional Private Name",
                }
            ],
        }
    )
    transcript, _ = source_and_facts()
    assert validate_speaker_roles(value, transcript) == {
        **snapshot(),
        "speakers": [{"speaker_id": "speaker_1", "role": projected, "is_account_holder": holder}],
    }


@pytest.mark.parametrize(
    "change",
    [
        "voice",
        "stale",
        "name",
        "hash",
        "unknown",
        "unattributed",
        "raw_you",
        "coerced_bool",
        "duplicate",
        "two_holders",
        "prospect_holder",
        "oversize",
        "empty_confirmed",
        "extra",
    ],
)
def test_invalid_snapshots_fail_with_content_free_diagnostic(change):
    transcript, _ = source_and_facts()
    roles = snapshot()
    row = roles["speakers"][0]
    if change == "voice":
        roles["origin"] = "voice_match"
    elif change == "stale":
        roles["transcript_revision"] = "old-transcript"
    elif change == "name":
        row["display_name"] = "Fictional Private Name"
    elif change == "hash":
        roles["map_revision"] = "not-a-hash"
    elif change in {"unknown", "unattributed"}:
        row["speaker_id"] = change
    elif change == "raw_you":
        row["role"] = "you"
    elif change == "coerced_bool":
        row["is_account_holder"] = 1
    elif change == "duplicate":
        roles["speakers"].append(deepcopy(row))
    elif change == "two_holders":
        roles["speakers"].append({**row, "speaker_id": "speaker_2"})
    elif change == "prospect_holder":
        row["role"] = "prospect"
    elif change == "oversize":
        roles["speakers"] = [deepcopy(row) for _ in range(33)]
    elif change == "empty_confirmed":
        roles["speakers"] = []
    else:
        roles["profile_name"] = "Fictional Private Name"
    before = deepcopy((roles, transcript))
    with pytest.raises(ValueError, match="^speaker_roles_snapshot_invalid$"):
        validate_speaker_roles(roles, transcript)
    assert (roles, transcript) == before


@pytest.mark.parametrize("origin", ["user_confirmed_roles", "channel_mapped_roles"])
def test_incomplete_authoritative_origin_is_refused_but_prediction_can_be_partial(origin):
    transcript, _ = source_and_facts()
    transcript["segments"][1]["speaker_id"] = "speaker_2"
    with pytest.raises(ValueError, match="^speaker_roles_snapshot_invalid$"):
        validate_speaker_roles(snapshot(origin), transcript)
    assert validate_speaker_roles(snapshot("text_predicted_roles"), transcript)["origin"] == (
        "text_predicted_roles"
    )
