"""Only identical canonical evaluators link provisional coaching suggestions."""

from copy import deepcopy

import pytest

from ac_platform.coaching.library import evaluator_key

MANIFEST = {
    "revision": "canonical-c5-v1",
    "config": {
        "input_sha256": "a" * 64,
        "provider": "fictional-offline",
        "model": "fictional-v1",
        "profile_sha256": "b" * 64,
        "coaching_prompt_revision": "coaching-v7",
        "report_language": "hi-Deva+en",
        "qualitative_pack_sha256": "c" * 64,
    },
}


def test_other_call_inputs_can_link_without_linking_different_recipes() -> None:
    changed = deepcopy(MANIFEST)
    changed["config"]["input_sha256"] = "d" * 64
    assert evaluator_key(changed, "recipe-1") == evaluator_key(MANIFEST, "recipe-1")
    assert evaluator_key(changed, "recipe-2") != evaluator_key(MANIFEST, "recipe-1")


@pytest.mark.parametrize(
    "field",
    [
        "provider",
        "model",
        "profile_sha256",
        "coaching_prompt_revision",
        "report_language",
        "qualitative_pack_sha256",
        "repair",
        "acquisition_c5_benchmark_approval_id",
    ],
)
def test_evaluator_boundaries_do_not_silently_link(field: str) -> None:
    changed = deepcopy(MANIFEST)
    changed["config"][field] = "different"
    assert evaluator_key(changed, "recipe-1") != evaluator_key(MANIFEST, "recipe-1")
