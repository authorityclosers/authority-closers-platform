"""AI on calls levels (owner, 21 Oct 2026): what each level runs and who it applies to."""

from uuid import uuid4

import pytest

from ac_platform.call_ai import policy, store


def test_each_level_says_which_paid_stage_it_leaves_out() -> None:
    assert policy.skipped_from("off") == "C2"  # no transcription at all
    assert policy.skipped_from("data_only") == "C4"  # transcript, no facts or coaching
    assert policy.skipped_from("full") is None
    # Auto runs in full until the call-type router (phase 2) exists.
    assert policy.effective("auto") == "full" and policy.skipped_from("auto") is None
    assert policy.SKIP_CODES == {"off": "ai_off", "data_only": "ai_data_only"}


def test_a_persons_own_level_beats_the_organisations_default() -> None:
    seller, other = uuid4(), uuid4()
    config = policy.validate({"default": "data_only", "people": {str(seller): "full"}})
    assert policy.resolve(config, seller) == ("full", "person")
    assert policy.resolve(config, other) == ("data_only", "organisation")
    # A guest upload with no account follows the organisation's default.
    assert policy.resolve(config, None) == ("data_only", "organisation")
    # Never saved: every call runs in full, as before this switch.
    assert policy.resolve(policy.defaults(), seller) == ("full", "organisation")


def test_setting_and_clearing_one_persons_level() -> None:
    seller = uuid4()
    config = policy.with_person(policy.defaults(), seller, "off")
    assert config == {"default": "full", "people": {str(seller): "off"}}
    assert policy.with_person(config, seller, None) == policy.defaults()


@pytest.mark.parametrize(
    "config",
    [
        {"default": "cheap"},
        {"default": "full", "people": {"not-a-person": "off"}},
        {"default": "full", "people": {str(uuid4()): "half"}},
        {"default": "full", "extra": True},
        {"default": "full", "people": {str(uuid4()): "off" for _ in range(2_001)}},
    ],
)
def test_bad_settings_are_refused_in_words(config: dict) -> None:
    with pytest.raises(policy.SettingsError):
        policy.validate(config)


def test_release_checks_and_upgraded_calls_always_run_in_full() -> None:
    seller = uuid4()
    saved = store.Settings(4, policy.validate({"default": "off", "people": {}}))
    assert store._decide(saved, seller, canary=False, upgraded=False).skipped_from == "C2"
    canary = store._decide(saved, seller, canary=True, upgraded=False)
    assert (canary.level, canary.source, canary.skipped_from) == ("full", "canary", None)
    # Staging's release check stops after the transcript (orchestrator, 13 Nov 2026).
    assert {"staging"} == policy.TRANSCRIPT_ONLY_CANARIES
    staging = store._decide(saved, seller, canary=True, upgraded=False, transcript_only=True)
    assert (staging.level, staging.source, staging.skipped_from) == ("data_only", "canary", "C4")
    upgraded = store._decide(saved, seller, canary=False, upgraded=True)
    assert (upgraded.level, upgraded.source, upgraded.settings_revision) == ("full", "upgrade", 4)


def test_a_saved_document_that_no_longer_validates_runs_calls_as_before() -> None:
    row = type("Row", (), {"revision": 7, "config": {"default": "retired-level"}})()
    assert store._settings(row) == store.Settings(7, policy.defaults())
    assert store._settings(None) == store.Settings(None, policy.defaults())


def _transcript(duration_ms: int, *turns: tuple[str, int, int]) -> dict:
    return {
        "duration_ms": duration_ms,
        "segments": [
            {"speaker_id": who, "start_ms": start, "end_ms": end, "text": "words"}
            for who, start, end in turns
        ],
    }


def test_short_calls_and_calls_without_a_conversation() -> None:
    # Owner, 21 Oct 2026: under a minute, or no conversation, keeps transcript + lead details.
    two_people = (("speaker_0", 0, 15_000), ("speaker_1", 15_000, 30_000))
    assert policy.short_call_reason(_transcript(45_000, *two_people)) == "short_call"
    assert policy.short_call_reason(_transcript(15_000, ("speaker_0", 0, 15_000))) == (
        "no_conversation"
    )
    # Five minutes under one speaker label may be a missed speaker split: never skipped.
    assert policy.short_call_reason(_transcript(300_000, ("speaker_0", 0, 300_000))) is None
    # Under a minute, one speaker (a voicemail, a ring-out message) is a short call.
    assert policy.short_call_reason(_transcript(40_000, ("speaker_0", 0, 40_000))) == ("short_call")
    # Two minutes where the other side says 5 seconds is no conversation either.
    lopsided = (("speaker_0", 0, 115_000), ("speaker_1", 115_000, 120_000))
    assert policy.short_call_reason(_transcript(120_000, *lopsided)) == "no_conversation"
    talking = (("speaker_0", 0, 50_000), ("speaker_1", 50_000, 90_000))
    assert policy.short_call_reason(_transcript(90_000, *talking)) is None
    # Without a duration, the last segment's end is the length.
    assert (
        policy.short_call_reason(
            {"segments": [dict(s) for s in _transcript(0, *two_people)["segments"]]}
        )
        == "short_call"
    )
    assert {"ai_short_call", "ai_no_conversation"}.issubset(policy.FAILURE_CODES)


def test_dead_air_is_no_conversation_before_the_length_check() -> None:
    # Test calls' R14 (14 Nov 2026): the line connects, one side says "Hello? Can you hear
    # me?" for about 10 seconds of a 65-second call. One speaker label over a minute used
    # to count as a conversation and got a full sales report.
    hello = (
        ("speaker_0", 1_000, 4_000),
        ("speaker_0", 9_000, 13_000),
        ("speaker_0", 30_000, 33_000),
    )
    assert policy.short_call_reason(_transcript(65_000, *hello)) == "no_conversation"
    # Checked before the length: under a minute with 15 seconds of speech is dead air, not
    # a short call.
    quiet = (("speaker_0", 0, 8_000), ("speaker_1", 20_000, 27_000))
    assert policy.short_call_reason(_transcript(45_000, *quiet)) == "no_conversation"
    # Nothing transcribed at all, however long the recording.
    assert policy.short_call_reason(_transcript(90_000)) == "no_conversation"
    # Every speaker counts together: 12 + 9 seconds over two minutes is 21 seconds of speech,
    # and the quieter side's 9 seconds is a two-sided call, so it is analysed.
    sparse = (("speaker_0", 0, 12_000), ("speaker_1", 60_000, 69_000))
    assert policy.short_call_reason(_transcript(120_000, *sparse)) is None
    # Untimed segments are not speech; a real conversation is never held by this rule.
    broken = (("speaker_0", 5_000, 5_000), ("speaker_1", 0, 300_000))
    assert policy.short_call_reason(_transcript(300_000, *broken)) is None
    assert policy.DEAD_AIR_SPEECH_MS == 20_000


def test_the_short_call_rule_is_off_only_where_tests_use_fixture_audio() -> None:
    assert policy.short_rule_applies("production")
    assert policy.short_rule_applies("development")
    assert not policy.short_rule_applies("test")
    assert not policy.short_rule_applies(None)
