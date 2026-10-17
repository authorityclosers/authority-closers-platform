"""A single visible processing choice remains bound to exact upload terms."""

from dataclasses import replace
from uuid import UUID

from ac_platform.conversation_intelligence.acquisition_processing import upload_policy
from ac_platform.conversation_intelligence.canary_cli import retention_allowed
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.intake import (
    PRIVACY_REVISION,
    UNTIL_DELETED_PRIVACY_REVISION,
    IntakePolicy,
)


def test_processing_notice_is_hashed_and_changes_when_retention_changes():
    policy = IntakePolicy(
        budget_scope_id=UUID(int=1),
        tenant_ids=frozenset({UUID(int=2)}),
        authorization_ref="ref:test/intake",
        retention_ref="ref:test/retention",
    )
    current = upload_policy(policy)
    digest = current.pop("policy_sha256")
    assert digest == content_hash(current)
    assert "AI service providers" in current["description"]
    assert "transcribe the recording" in current["description"]
    assert "up to 7 days" in current["description"]
    assert "does not send audio" not in current["description"]
    assert "separate provider plan" not in current["description"]
    shorter = upload_policy(replace(policy, retention_days=3))
    assert shorter["policy_sha256"] != digest
    assert "up to 3 days" in shorter["description"]
    # The intake receipt is still zero-cost local work. The separately bound
    # provider plan retains its own exact fingerprint and budget acceptance.
    assert current["max_cost_paise"] == 0


def _policy(**overrides: object) -> IntakePolicy:
    values: dict[str, object] = {
        "budget_scope_id": UUID(int=1),
        "tenant_ids": frozenset({UUID(int=2)}),
        "authorization_ref": "ref:test/intake",
        "retention_ref": "ref:test/retention",
    }
    values.update(overrides)
    return IntakePolicy(**values)  # type: ignore[arg-type]


def test_terms_name_the_sealed_ai_providers_and_the_names_are_in_the_fingerprint():
    named = upload_policy(_policy(ai_processors=("elevenlabs", "gemini")))
    assert (
        "sends the recording and its transcript to its AI service providers, "
        "ElevenLabs and Google Gemini, to transcribe the call and prepare and score "
        "your coaching report."
    ) in named["description"]
    assert named["privacy_details"].startswith("ElevenLabs and Google Gemini receive")
    assert named["privacy_revision"] == PRIVACY_REVISION == "local-private-audio-v2"
    view = dict(named)
    digest = view.pop("policy_sha256")
    assert digest == content_hash(view)
    other = upload_policy(_policy(ai_processors=("elevenlabs", "gemini", "groq")))
    assert "ElevenLabs, Google Gemini and Groq" in other["description"]
    assert other["policy_sha256"] != digest
    assert len(named["description"]) <= 3000  # the web parser's bound


def test_seven_day_terms_say_the_call_is_deleted_after_the_week():
    week = upload_policy(_policy(ai_processors=("gemini",)))
    assert week["retention_mode"] == "days"
    assert "stay private for up to 7 days" in week["description"]
    assert "for up to 7 days, then deletes them." in week["privacy_details"]


def test_keep_until_deleted_terms_and_revision():
    keep = _policy(
        retention_ref="ref:retention/sales-xray-until-deleted-v1",
        retention_days=3650,
        ai_processors=("elevenlabs", "gemini"),
    )
    assert keep.keeps_until_deleted and not keep.keeps_for_training
    view = upload_policy(keep)
    assert view["retention_mode"] == "until_deleted"
    assert view["privacy_revision"] == UNTIL_DELETED_PRIVACY_REVISION
    assert (
        "Your recording and report are kept privately until you delete them."
        in (view["description"])
    )
    assert "until you delete the call or ask us to delete it." in view["privacy_details"]
    assert "days" not in view["description"] and "training" not in view["description"]
    assert "coaching AI" not in view["privacy_details"]
    assert keep.retention_sentence() == (
        "Your recording stays in AC's private storage until you delete it. "
    )


def test_canary_accepts_keep_until_deleted_in_production_but_never_training():
    until = "ref:retention/sales-xray-until-deleted-v1"
    training = "ref:retention/sales-xray-keep-for-training-v1"
    assert retention_allowed("production", 3650, until)
    assert not retention_allowed("production", 3650, training)
    assert retention_allowed("staging", 3650, training)
    assert retention_allowed("production", 7, "ref:retention/sales-xray-seven-days-v1")
    assert not retention_allowed("production", 8, "ref:retention/sales-xray-seven-days-v1")
