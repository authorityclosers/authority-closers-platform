"""Deterministic dependency receipts; synthetic hashes only, no inference or IO."""

from dataclasses import FrozenInstanceError, replace

import pytest

from ac_platform.conversation_intelligence.checkpoints import (
    STAGE_PARENTS,
    SourceBinding,
    assert_same_artifact,
    build_checkpoint,
    canonical,
    invalidated_stages,
)


def graph(**overrides):
    source = SourceBinding("tenant-a", "recording-a", "1" * 64, "source-1")
    nodes = {}
    for stage, parents in STAGE_PARENTS.items():
        nodes[stage] = build_checkpoint(
            source,
            stage,
            "v1",
            overrides.get(stage, {}),
            [nodes[parent] for parent in parents],
            "2" * 64,
        )
    return nodes


def test_profile_and_judge_change_reuse_transcript_and_measurements():
    old = graph(C5={"profile": "dipak-1", "judge": "judge-1"})
    changed = graph(C5={"profile": "dipak-2", "judge": "judge-2"})
    assert all(old[s].cache_key == changed[s].cache_key for s in ("C0", "C1", "C2", "C3", "C4"))
    assert all(old[s].cache_key != changed[s].cache_key for s in ("C5", "C6"))
    assert invalidated_stages({"profile", "judge"}) == {"C5", "C6"}


def test_transcript_and_measurement_branches_are_independent():
    assert invalidated_stages({"transcript"}) == {"C2", "C3", "C4", "C5", "C6"}
    assert invalidated_stages({"measurement"}) == {"C1", "C3", "C4", "C5", "C6"}
    assert invalidated_stages({"source"}) == set(STAGE_PARENTS)
    assert invalidated_stages(set()) == set()
    with pytest.raises(ValueError, match="unknown changed layer"):
        invalidated_stages({"accident"})


def test_acoustic_window_profiles_are_explicit_measurement_cache_inputs():
    audioatlas = graph(C1={"acoustic_profile": "audioatlas-40ms", "window_ms": 40})
    signallab = graph(C1={"acoustic_profile": "signallab-80ms", "window_ms": 80})
    assert audioatlas["C1"].cache_key != signallab["C1"].cache_key
    assert audioatlas["C2"].cache_key == signallab["C2"].cache_key
    assert audioatlas["C3"].cache_key != signallab["C3"].cache_key


def test_cache_isolated_by_tenant_recording_source_and_revision():
    original = graph()["C0"]
    for field, value in (
        ("tenant_id", "tenant-b"),
        ("recording_id", "recording-b"),
        ("source_sha256", "3" * 64),
        ("source_revision", "source-2"),
    ):
        assert replace(original, binding=replace(original.binding, **{field: value})).cache_key != (
            original.cache_key
        )


def test_checkpoint_is_immutable_and_payload_conflict_is_not_overwritten():
    original = graph()["C0"]
    with pytest.raises(FrozenInstanceError):
        original.revision = "changed"
    assert_same_artifact(original, original)
    different = replace(original, payload_sha256="3" * 64)
    assert different.cache_key == original.cache_key
    with pytest.raises(ValueError, match="immutable checkpoint conflict"):
        assert_same_artifact(original, different)
    assert replace(different, replicate="independent-2").cache_key != original.cache_key


def test_parent_manifest_binds_payload_not_just_derivation():
    nodes = graph()
    changed_parent = replace(nodes["C0"], payload_sha256="3" * 64)
    changed = build_checkpoint(nodes["C1"].binding, "C1", "v1", {}, [changed_parent], "2" * 64)
    assert changed.cache_key != nodes["C1"].cache_key


def test_requires_exact_same_source_parent_set():
    nodes = graph()
    for parents in ([], [nodes["C1"]], [nodes["C1"], nodes["C1"]]):
        with pytest.raises(ValueError, match="exact stage parents"):
            build_checkpoint(nodes["C3"].binding, "C3", "v1", {}, parents, "2" * 64)
    wrong = replace(nodes["C0"], binding=replace(nodes["C0"].binding, tenant_id="tenant-b"))
    with pytest.raises(ValueError, match="cross-source or cross-tenant"):
        build_checkpoint(nodes["C1"].binding, "C1", "v1", {}, [wrong], "2" * 64)


@pytest.mark.parametrize("config", [{"profile": "v2"}, {"nested": [{"judge_revision": "v2"}]}])
def test_global_coaching_config_rejected_at_cheap_checkpoint(config):
    nodes = graph()
    with pytest.raises(ValueError, match="coaching configuration"):
        build_checkpoint(nodes["C2"].binding, "C2", "v1", config, [nodes["C0"]], "2" * 64)


def test_json_and_hash_validation():
    assert canonical({"b": 2, "a": 1}) == canonical({"a": 1, "b": 2})
    with pytest.raises(ValueError):
        canonical({"not_json": float("nan")})
    with pytest.raises(ValueError, match="source_sha256"):
        SourceBinding("a", "r", "bad", "v1")
