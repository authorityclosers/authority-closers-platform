"""Fictional candidate-rule proofs; these fixtures do not confirm the rubric."""

from copy import deepcopy

import pytest

from ac_platform.conversation_intelligence import reports
from ac_platform.conversation_intelligence.call_map import QUALIFICATION_ITEMS
from tests.unit.conversation_intelligence.test_coaching_v5_depth import _payload, _transcript


def fixture(*, v7=True):
    transcript = _transcript()
    transcript["segments"][1]["speaker_id"] = "speaker_2"
    for segment_id, speaker_id in [("s3", "speaker_3"), ("s4", "unattributed")]:
        transcript["segments"].append(
            {**transcript["segments"][0], "id": segment_id, "speaker_id": speaker_id}
        )
    if v7:
        for index, segment in enumerate(deepcopy(transcript["segments"]), start=5):
            transcript["segments"].append({**segment, "id": f"s{index}"})
    profile = reports.load_report_profile()
    payload = _payload(transcript, profile=profile)
    for row in payload["dimensions"]:
        row.update(status="unknown", evidence=[])
    snapshot = {
        "origin": "user_confirmed_roles",
        "transcript_revision": transcript["revision"],
        "map_revision": "b" * 64,
        "speakers": [
            {"speaker_id": "speaker_1", "role": "seller", "is_account_holder": True},
            {"speaker_id": "speaker_2", "role": "prospect", "is_account_holder": False},
            {"speaker_id": "speaker_3", "role": "other", "is_account_holder": False},
        ],
    }
    if v7:
        payload["call_map"] = {
            "version": "call-map/1",
            "verdict_line": "Evidence remains bounded.",
            "call_purpose": {"kind": "unclear", "evidence": []},
            "speakers": [
                {"speaker_id": row["speaker_id"], "role": row["role"]}
                for row in snapshot["speakers"]
            ]
            + [{"speaker_id": "unattributed", "role": "other"}],
            "phases": [{"name": "opening", "start_ms": 0}],
            "time_promise": None,
            "outcome": {
                "kind": "none",
                "next_step_rung": "none",
                "next_step_when": None,
                "evidence": [],
            },
            "signals": [],
            "pitch_items": [],
            "pains": [],
            "money": [],
            "claims": [],
            "qualification_gaps": list(QUALIFICATION_ITEMS),
            "qualification_confirmed": [],
            "prospect_tasks": [],
            "seller_tasks": [],
            "objections": [],
            "prospect_facts": [],
        }
    return transcript, profile, payload, snapshot


@pytest.mark.parametrize("dimension_id", sorted(reports.PROSPECT_DIMENSION_IDS))
@pytest.mark.parametrize("status", ["observed", "conflicted"])
@pytest.mark.parametrize(
    "segments",
    [
        ["s1"],
        ["s2"],
        ["s1", "s2"],
        ["s3"],
        ["s4"],
        [],
        ["s1", "s5"],
        ["s2", "s6"],
        ["s3", "s7"],
        ["s4", "s8"],
    ],
)
def test_only_confirmed_dimensions_require_prospect_support(
    monkeypatch, dimension_id, status, segments
):
    transcript, profile, payload, roles = fixture()
    monkeypatch.setattr(reports, "CONFIRMED_PROSPECT_DIMENSIONS", frozenset({dimension_id}))
    dimension = next(row for row in payload["dimensions"] if row["dimension_id"] == dimension_id)
    dimension.update(status=status, evidence=[{"segment_id": segment} for segment in segments])
    before = deepcopy((payload, roles))
    kwargs = dict(profile=profile, coaching_prompt_revision="coaching-v7", speaker_roles=roles)
    if status == "conflicted" and not segments:
        with pytest.raises(reports.ReportError, match="^report_dimension_evidence_required$"):
            reports.parse_report_draft(payload, transcript, **kwargs)
    elif status == "observed" and len(set(segments)) < 2:
        draft = reports.parse_report_draft(payload, transcript, **kwargs)
        assert next(row for row in draft.dimensions if row.dimension_id == dimension_id).status == (
            "partial" if segments else "insufficient_evidence"
        )
    elif "s2" in segments:
        draft = reports.parse_report_draft(payload, transcript, **kwargs)
        assert (
            next(row for row in draft.dimensions if row.dimension_id == dimension_id).status
            == status
        )
    else:
        with pytest.raises(
            reports.ReportError, match="^report_dimension_prospect_evidence_required$"
        ) as error:
            reports.parse_report_draft(payload, transcript, **kwargs)
        assert error.value.dimension_ids == (dimension_id,)
    assert (payload, roles) == before


@pytest.mark.parametrize(
    "change",
    [
        {"origin": origin}
        for origin in ["text_predicted_roles", "model_named_roles", "unverified_provider_labels"]
    ]
    + [
        {"origin": None},
        {"transcript_revision": "stale"},
        {"transcript_revision": None},
        {"map_revision": None},
    ],
)
def test_unverified_stale_or_incomplete_snapshots_skip(monkeypatch, change):
    transcript, profile, payload, roles = fixture()
    monkeypatch.setattr(reports, "CONFIRMED_PROSPECT_DIMENSIONS", reports.PROSPECT_DIMENSION_IDS)
    payload["dimensions"][0].update(status="observed", evidence=[{"segment_id": "s1"}])
    roles.update(change)
    reports.parse_report_draft(
        payload,
        transcript,
        profile=profile,
        coaching_prompt_revision="coaching-v7",
        speaker_roles=roles,
    )


@pytest.mark.parametrize("change", ["duplicate", "unknown", "missing", "no_prospect", "none"])
def test_malformed_or_prospect_free_map_never_authorizes_the_rule(monkeypatch, change):
    transcript, profile, payload, roles = fixture()
    monkeypatch.setattr(reports, "CONFIRMED_PROSPECT_DIMENSIONS", reports.PROSPECT_DIMENSION_IDS)
    payload["dimensions"][0].update(status="observed", evidence=[{"segment_id": "s1"}])
    if change == "duplicate":
        roles["speakers"].append(deepcopy(roles["speakers"][0]))
    elif change == "unknown":
        roles["speakers"][1]["speaker_id"] = "unknown"
    elif change == "missing":
        roles.pop("origin")
    elif change == "no_prospect":
        roles["speakers"][1]["role"] = "other"
    else:
        roles = None
    reports.parse_report_draft(
        payload,
        transcript,
        profile=profile,
        coaching_prompt_revision="coaching-v7",
        speaker_roles=roles,
    )


@pytest.mark.parametrize(
    "revision", ["coaching-v3", "coaching-v4", "coaching-v5", "coaching-v6", "coaching-v7"]
)
def test_legacy_canonical_and_unconfirmed_paths_are_unchanged(monkeypatch, revision):
    transcript, profile, payload, roles = fixture(v7=revision == "coaching-v7")
    payload["dimensions"][0].update(status="observed", evidence=[{"segment_id": "s1"}])
    kwargs = dict(profile=profile, coaching_prompt_revision=revision)
    # The empty confirmed subset is the shipping state until P-A is recorded.
    assert not reports.CONFIRMED_PROSPECT_DIMENSIONS
    reports.parse_report_draft(payload, transcript, speaker_roles=roles, **kwargs)
    monkeypatch.setattr(reports, "CONFIRMED_PROSPECT_DIMENSIONS", frozenset({"qualification"}))
    draft = reports.parse_report_draft(payload, transcript, speaker_roles=roles, **kwargs)
    monkeypatch.setattr(reports, "CONFIRMED_PROSPECT_DIMENSIONS", reports.PROSPECT_DIMENSION_IDS)
    reread = reports.parse_report_draft(
        draft.model_dump(mode="json"),
        transcript,
        canonical_read=True,
        speaker_roles=roles,
        **kwargs,
    )
    assert reread == draft
    if revision != "coaching-v7":
        assert (
            reports.parse_report_draft(payload, transcript, speaker_roles=roles, **kwargs) == draft
        )


def test_literal_validation_precedes_the_prospect_predicate(monkeypatch):
    transcript, profile, payload, roles = fixture()
    monkeypatch.setattr(reports, "CONFIRMED_PROSPECT_DIMENSIONS", reports.PROSPECT_DIMENSION_IDS)
    payload["dimensions"][0].update(
        status="observed",
        evidence=[{"segment_id": "s2", "quote": "invented", "start_ms": 1000, "end_ms": 1900}],
    )
    with pytest.raises(reports.ReportError, match="report_evidence_quote_mismatch"):
        reports.parse_report_draft(
            payload,
            transcript,
            profile=profile,
            coaching_prompt_revision="coaching-v7",
            speaker_roles=roles,
        )


@pytest.mark.parametrize("status", ["insufficient_evidence", "not_applicable", "unknown"])
def test_non_observed_states_skip_prospect_rule_and_other_dimensions_use_d8(monkeypatch, status):
    transcript, profile, payload, roles = fixture()
    monkeypatch.setattr(reports, "CONFIRMED_PROSPECT_DIMENSIONS", reports.PROSPECT_DIMENSION_IDS)
    for row in payload["dimensions"]:
        row.update(
            status=status if row["dimension_id"] in reports.PROSPECT_DIMENSION_IDS else "observed",
            evidence=[],
        )
    draft = reports.parse_report_draft(
        payload,
        transcript,
        profile=profile,
        coaching_prompt_revision="coaching-v7",
        speaker_roles=roles,
    )
    assert [row.status for row in draft.dimensions] == [
        status if row["dimension_id"] in reports.PROSPECT_DIMENSION_IDS else "insufficient_evidence"
        for row in payload["dimensions"]
    ]


@pytest.mark.parametrize("origin", ["user_confirmed_roles", "channel_mapped_roles"])
def test_output_roles_cannot_replace_frozen_roles_or_supply_truncated_support(monkeypatch, origin):
    transcript, profile, payload, roles = fixture()
    roles["origin"] = origin
    monkeypatch.setattr(reports, "CONFIRMED_PROSPECT_DIMENSIONS", reports.PROSPECT_DIMENSION_IDS)
    payload["speaker_roles"] = {
        **roles,
        "speakers": [{"speaker_id": "speaker_1", "role": "prospect", "is_account_holder": False}],
    }
    payload["dimensions"][0].update(
        status="observed", evidence=[{"segment_id": "s1"}, {"segment_id": "s5"}]
    )
    kwargs = dict(profile=profile, coaching_prompt_revision="coaching-v7", speaker_roles=roles)
    with pytest.raises(reports.ReportError, match="^report_dimension_prospect_evidence_required$"):
        reports.parse_report_draft(payload, transcript, **kwargs)
    payload["dimensions"][0]["evidence"] = [{"segment_id": "s1"}] * 8 + [{"segment_id": "s2"}]
    with pytest.raises(reports.ReportError, match="^report_dimension_prospect_evidence_required$"):
        reports.parse_report_draft(payload, transcript, **kwargs)
