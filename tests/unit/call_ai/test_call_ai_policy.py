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
    upgraded = store._decide(saved, seller, canary=False, upgraded=True)
    assert (upgraded.level, upgraded.source, upgraded.settings_revision) == ("full", "upgrade", 4)


def test_a_saved_document_that_no_longer_validates_runs_calls_as_before() -> None:
    row = type("Row", (), {"revision": 7, "config": {"default": "retired-level"}})()
    assert store._settings(row) == store.Settings(7, policy.defaults())
    assert store._settings(None) == store.Settings(None, policy.defaults())
