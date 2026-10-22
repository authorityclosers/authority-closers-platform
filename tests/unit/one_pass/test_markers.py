"""The one-pass request identifiers: v1 is pinned (sealed configurations depend on it), v2 is
its own recipe and marker."""

from ac_platform.one_pass import markers


def test_v1_identifiers_are_unchanged() -> None:
    assert markers.RECIPE == "one-pass-facts-v1"
    assert markers.PROMPT_REVISION == "one-pass-v1"
    assert markers.MARKER == "FACT_OUTPUT: one-pass-facts-v1."


def test_v2_is_its_own_recipe_and_marker() -> None:
    assert markers.RECIPE_V2 == "one-pass-facts-v2"
    assert markers.PROMPT_REVISION_V2 == "one-pass-v2"
    assert markers.MARKER_V2 == "FACT_OUTPUT: one-pass-facts-v2."
    assert not markers.MARKER_V2.startswith(markers.MARKER)
    assert frozenset({markers.RECIPE, markers.RECIPE_V2}) == markers.RECIPES
    # Until the v2 wiring lands, a v2 prompt is not taken for the v1 request.
    assert not markers.is_one_pass(markers.MARKER_V2 + "\n...")
